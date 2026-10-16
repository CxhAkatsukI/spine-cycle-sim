"""Wait on a pinned live source-build invocation, then admit bounded board work."""

import json
import math
from pathlib import Path
import re
import sys
import time

from spine_cycle_sim.experiments.campaign_runtime import atomic_write_json
from spine_cycle_sim.experiments.evaluation_impact.common_g.continuous_board.execution import supervisor as waiting
from spine_cycle_sim.experiments.sharded_k4_stages.link_runtime import run_link
from spine_cycle_sim.experiments.sharded_k4_stages.row_line.directory_tile.hardware.concurrent import Lease
from spine_cycle_sim.experiments.sharded_k4_stages.row_line.directory_tile.hardware.containment import current, other_builds, verify
from spine_cycle_sim.experiments.upstream_controls.execution import available_memory_bytes
from .. import artifact
from ..source_build.snapshot import unchanged
from ..source_build import configuration as config
from . import admission, analysis, preparation, worker


def validate(unit, invocation, device, maximum_wait, poll_seconds):
    if (not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.@:-]*\.service", unit) or
            not re.fullmatch(r"[0-9a-f]{32}", invocation) or type(device) is not int or device not in (0, 1) or
            any(type(value) not in (int, float) or not math.isfinite(value) or value <= 0
                for value in (maximum_wait, poll_seconds))):
        raise ValueError("known board, exact source-build invocation and finite wait bounds required")


def route_finished(state, invocation, review_retained_analysis_failure=False):
    if (review_retained_analysis_failure is True and state["LoadState"] == "loaded" and
            state["InvocationID"] == invocation and state["ActiveState"] == "failed" and
            state["SubState"] == "failed" and state["Result"] == "exit-code" and
            state["MainPID"] == "0" and state["ExecMainStatus"] == "1"):
        # Eligibility for read-only review, never hardware or board admission.
        return True
    return waiting.route_finished(state, invocation)


def run(audit, control, route, output, *, route_unit, route_invocation,
        device=1, maximum_wait=86400, poll_seconds=30, topology=config.DEFAULT_TOPOLOGY,
        review_retained_analysis_failure=False):
    validate(route_unit, route_invocation, device, maximum_wait, poll_seconds)
    config.counts(topology)
    if type(review_retained_analysis_failure) is not bool:
        raise ValueError("retained analysis review requires an explicit boolean")
    output.mkdir(parents=True, exist_ok=False)
    report = {"status": "PREPARING", "configuration": topology,
              "errors": [], "route_states": [], "device_index": device,
              "route_unit": route_unit, "route_invocation": route_invocation,
              "review_retained_analysis_failure": review_retained_analysis_failure,
              "maximum_wait_seconds": maximum_wait, "poll_seconds": poll_seconds,
              "board_launch_attempted": False, "board_programmed": False,
              "hardware_timing_measured": False, "publication_match": False,
              "convergence_measured": False, "host_inclusive_measured": False}
    lease = None
    save = lambda: atomic_write_json(output / "results.json", report)
    save()
    try:
        group = current()
        report["containment"] = verify(group, memory_gib=8)
        if int(report["containment"]["limits"]["memory.high"]) > 7 * 1024**3:
            raise ValueError("board supervisor requires memory.high at most 7 GiB")
        plan = preparation.prepare(audit, control, route, topology=topology)
        plan.update(device_index=device)
        atomic_write_json(output / "plan.json", plan)
        report.update(boundary=plan["boundary"], pins=preparation.unique(
            [*plan["pins"], artifact.identity(output / "plan.json")]), expected_board_rows=18)
        started = time.monotonic()
        while True:
            unchanged(report["pins"])
            state = waiting.service_state(route_unit)
            if not report["route_states"] or report["route_states"][-1] != state:
                report["route_states"].append(state)
            report.update(status="WAITING_FOR_REQUIRED_SOURCE_ROUTE", waited_seconds=time.monotonic() - started)
            save()
            if route_finished(state, route_invocation, review_retained_analysis_failure):
                break
            if report["waited_seconds"] >= maximum_wait:
                raise TimeoutError("required source-build wait expired; no board execution")
            time.sleep(min(poll_seconds, maximum_wait - report["waited_seconds"]))
        if review_retained_analysis_failure:
            admission.validate_result(json.loads((route / "results.json").read_text()), topology, True)
        # Reserve full peer budgets before extraction or board work, not while waiting.
        lease = Lease(Path.home() / ".cache/spine-cycle-sim/compiler-reservations", group)
        report["admission"] = lease.sample(available_memory_bytes(), other_builds(), preparation.POLICY, commit=True)
        save()
        if not report["admission"]["admitted"]:
            raise ValueError("full finite peer budgets plus reserve do not fit; no board launch")
        review_options = {"review_retained_analysis_failure": True} if review_retained_analysis_failure else {}
        checked = admission.review(route, output / "routed_admission", topology=topology, **review_options)
        report["routed_admission"] = checked
        report["pins"] = preparation.unique([*report["pins"], *checked["pins"]])
        unchanged(report["pins"])
        if not route_finished(waiting.service_state(route_unit), route_invocation, review_retained_analysis_failure):
            raise ValueError("required source route is no longer terminal")
        job = {**plan, "xclbin": checked["xclbin"], "pins": report["pins"]}
        atomic_write_json(output / "manifest.json", job)
        report["status"] = "ROUTE_ADMITTED_STARTING_GUARDED_WORKER"
        save()
        command = [str(Path(sys.executable).resolve()), "-m", worker.__package__ + ".worker",
                   "--manifest", str(output / "manifest.json"), "--output", str(output / "board")]
        report["execution"] = run_link(command, Path.cwd(), output / "worker", timeout=11200,
            tree_memory_gib=8, reserve_gib=32, poll_seconds=0.2)
        save()
        execution = report["execution"]
        if execution["exit_code"] or execution["stop_reason"] != "process_exit" or execution["cleanup_snapshot_error"]:
            raise ValueError("guarded worker failed or reached its resource bound; no reset/retry")
        child = json.loads((output / "board/results.json").read_text())
        if (child["status"] != analysis.pass_status(topology) or child["errors"] or child["board_programmed"] is not True or
                child.get("configuration", config.DEFAULT_TOPOLOGY) != topology or
                child["hardware_timing_measured"] is not True or
                any(child.get(key) is not False for key in
                    ("publication_match", "convergence_measured", "host_inclusive_measured"))):
            raise ValueError("complete guarded board matrix required")
        for row in child["rows"]:
            case = next(case for case in plan["cases"] if case["graph"] == row["graph"] and case["binding"] == row["binding"])
            destination = Path(row["directory"])
            observed = json.loads((destination / "result.json").read_text())
            if observed != row["observation"] or analysis.inspect(observed, destination, case,
                    child["runtime"]["device"]["bdf"]) != row["analysis"]:
                raise ValueError("raw board observation or independent recheck differs")
        if child["summaries"] != analysis.matrix(child["rows"]):
            raise ValueError("complete board summary differs")
        unchanged(child["pins"])
        unchanged(report["pins"])
        report.update(status=analysis.pass_status(topology), board_launch_attempted=True, board_programmed=True,
                      hardware_timing_measured=True, child=artifact.identity(output / "board/results.json"),
                      summaries=child["summaries"])
    except BaseException as error:
        child_path = output / "board/results.json"
        if child_path.is_file():
            try:
                child = json.loads(child_path.read_text())
                report.update({key: child.get(key) for key in
                    ("board_launch_attempted", "board_programmed", "hardware_timing_measured")})
                report["child"] = artifact.identity(child_path)
            except (OSError, ValueError, KeyError, TypeError) as child_error:
                report["errors"].append("child report unreadable: " + repr(child_error))
        report["status"] = "FAILED_RETAINED"
        report["errors"].append(repr(error))
        save()
        raise
    finally:
        if lease is not None:
            lease.release()
        report["memory_events_after"] = (current() / "memory.events").read_text()
        save()
    return report
