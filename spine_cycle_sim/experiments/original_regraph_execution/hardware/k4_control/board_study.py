"""Admit one exact returned FullPR link, then independently recheck the K4 matrix."""

import argparse
import json
from pathlib import Path
import sys
import time

from spine_cycle_sim.experiments.campaign_runtime import atomic_write_json
from spine_cycle_sim.experiments.evaluation_impact.common_g.complete_pipeline.hardware.algorithm_build import admission, follow
from spine_cycle_sim.experiments.evaluation_impact.common_g.continuous_board.execution import supervisor as waiting
from spine_cycle_sim.experiments.sharded_k4_stages.link_runtime import run_link
from spine_cycle_sim.experiments.sharded_k4_stages.row_line.directory_tile.hardware.concurrent import Lease
from spine_cycle_sim.experiments.sharded_k4_stages.row_line.directory_tile.hardware.containment import current, other_builds, verify
from spine_cycle_sim.experiments.upstream_controls.execution import available_memory_bytes
from .. import artifact
from ..board_execution.preparation import POLICY, unique
from ..board_execution.supervisor import validate
from ..source_build.snapshot import unchanged
from . import analysis, board_analysis, board_matrix, board_plan, board_worker

READY = "MATCHED_K4_BOARD_PLAN_RECHECKED_NOT_FPGA"


def returned_result(directory):
    path = directory / "results.json"
    report = json.loads(path.read_text())
    if (report.get("status") != follow.PASS or report.get("errors") != [] or
            report.get("algorithm") != "full_pagerank" or report.get("board_requested") is not False or
            any(report.get(key) is not False for key in follow.artifacts.FLAGS)):
        raise ValueError("strictly admitted FullPR return required before K4 board execution")
    unchanged([*report["pins"], report["admission"]])
    return report, artifact.identity(path)


def recheck(child, plan):
    if (child.get("status") != board_matrix.PASS or child.get("errors") != [] or
            child.get("board_launch_attempted") is not True or child.get("board_programmed") is not True or
            child.get("hardware_timing_measured") is not True or
            child.get("source_contract") != plan["source_contract"] or
            child.get("routed_candidate") != plan["xclbin"] or
            any(child.get(key) is not False for key in board_plan.CLAIMS) or len(child.get("attempts", [])) != 12):
        raise ValueError("complete independently checked twelve-run K4 FPGA result required")
    names = {f"r{repeat}_{case['graph']}_{case['binding']}" for repeat in range(3)
             for case in plan["cases"] if case["status"] != analysis.UNSUPPORTED}
    if ({attempt["name"] for attempt in child["attempts"]} != names or any(
            type(attempt.get("exit_code")) is not int or attempt["exit_code"] != 0 or
            attempt.get("timed_out") is not False or attempt.get("lease_fd_forwarded") is not True
            for attempt in child["attempts"])):
        raise ValueError("every declared K4 attempt must finish under its forwarded lease")
    for row in child["rows"]:
        case = next(case for case in plan["cases"] if case["graph"] == row["graph"] and case["binding"] == row["binding"])
        if case["status"] == analysis.UNSUPPORTED:
            continue
        directory = Path(row["directory"])
        observed = json.loads((directory / "result.json").read_text())
        if (observed != row["observation"] or board_analysis.readback(observed, directory, case,
                child["runtime"]["device"]["bdf"]) != row["analysis"]):
            raise ValueError("raw K4 readback or independent board analysis changed")
    summaries = board_matrix.summarize(child["rows"], plan["cases"])
    if child.get("summaries") != summaries:
        raise ValueError("complete K4 board summaries differ")
    unchanged(child["pins"])
    return summaries


def run(preflight, sources, returned, output, *, return_unit, return_invocation, device=1,
        maximum_wait=133200, poll_seconds=30, execute=False):
    validate(return_unit, return_invocation, device, maximum_wait, poll_seconds)
    if type(execute) is not bool:
        raise ValueError("explicit execute boolean required")
    output.mkdir(parents=True, exist_ok=False)
    report = {"status": "PREPARING", "errors": [], "states": [], "device_index": device,
              "return_unit": return_unit, "return_invocation": return_invocation,
              "maximum_wait_seconds": maximum_wait, "poll_seconds": poll_seconds,
              "execute_requested": execute, "board_launch_attempted": False, "board_programmed": False,
              "hardware_timing_measured": False, **dict.fromkeys(board_plan.CLAIMS, False)}
    save = lambda: atomic_write_json(output / "results.json", report)
    lease = None
    save()
    try:
        group = current()
        report["containment"] = verify(group, memory_gib=8)
        if int(report["containment"]["limits"]["memory.high"]) > 7 * 1024**3:
            raise ValueError("K4 supervisor requires memory.high at most 7 GiB")
        plan = board_plan.prepare(preflight, sources)
        plan["device_index"] = device
        atomic_write_json(output / "plan.json", plan)
        report.update(pins=unique([*plan["pins"], artifact.identity(output / "plan.json")]),
                      source_contract=plan["source_contract"], predeclared_rows=18,
                      executable_rows=12, unsupported_rows=6)
        if not execute:
            report["status"] = READY
            return report
        started = time.monotonic()
        while True:
            unchanged(report["pins"])
            state = waiting.service_state(return_unit)
            if not report["states"] or report["states"][-1] != state:
                report["states"].append(state)
            report.update(status="WAITING_FOR_EXACT_ADMITTED_FULLPR_RETURN", waited_seconds=time.monotonic() - started)
            save()
            if waiting.route_finished(state, return_invocation):
                break
            if report["waited_seconds"] >= maximum_wait:
                raise TimeoutError("exact admitted FullPR return wait expired; no board launch")
            time.sleep(min(poll_seconds, maximum_wait - report["waited_seconds"]))
        returned_report, returned_pin = returned_result(returned)
        report["pins"] = unique([*report["pins"], returned_pin, *returned_report["pins"], returned_report["admission"]])
        lease = Lease(Path.home() / ".cache/spine-cycle-sim/compiler-reservations", group)
        while True:
            unchanged(report["pins"])
            report.update(status="WAITING_FOR_FINITE_BOARD_MEMORY_BUDGET", waited_seconds=time.monotonic() - started)
            report["admission"] = lease.sample(available_memory_bytes(), other_builds(), POLICY, commit=True)
            save()
            if report["admission"]["admitted"]:
                break
            if report["waited_seconds"] >= maximum_wait:
                raise TimeoutError("finite peer budgets plus reserve did not fit; no board launch")
            time.sleep(min(poll_seconds, maximum_wait - report["waited_seconds"]))
        checked = admission.review(returned / "returned", sources, output / "routed_admission",
                                   receipt_sha256=returned_report["receipt_sha256"])
        if checked["algorithm"] != "full_pagerank":
            raise ValueError("actual K4 control requires the FullPR ABI")
        report["pins"] = unique([*report["pins"], *checked["pins"], checked["candidate"],
                                 artifact.identity(output / "routed_admission/summary.json")])
        job = {**plan, "pins": report["pins"], "xclbin": checked["candidate"]}
        unchanged(report["pins"])
        if not waiting.route_finished(waiting.service_state(return_unit), return_invocation):
            raise ValueError("required FullPR return no longer terminal")
        atomic_write_json(output / "manifest.json", job)
        report["status"] = "FULLPR_ROUTE_ADMITTED_STARTING_K4_WORKER"
        save()
        command = [str(Path(sys.executable).resolve()), "-m", board_worker.__name__,
                   "--manifest", str(output / "manifest.json"), "--output", str(output / "board")]
        report["execution"] = run_link(command, Path.cwd(), output / "worker", timeout=11200,
            tree_memory_gib=8, reserve_gib=32, poll_seconds=0.2)
        save()
        result = report["execution"]
        if result["exit_code"] or result["stop_reason"] != "process_exit" or result["cleanup_snapshot_error"]:
            raise ValueError("K4 worker failed or exceeded resource bounds; no reset or retry")
        child = json.loads((output / "board/results.json").read_text())
        report["summaries"] = recheck(child, job)
        unchanged(report["pins"])
        report.update(status=board_matrix.PASS, board_launch_attempted=True, board_programmed=True,
                      hardware_timing_measured=True, child=artifact.identity(output / "board/results.json"))
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
        raise
    finally:
        if lease is not None:
            lease.release()
        report["memory_events_after"] = (current() / "memory.events").read_text()
        save()
    return report


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("preflight", "sources", "returned", "output"):
        parser.add_argument("--" + name, required=True, type=Path)
    parser.add_argument("--return-unit", required=True)
    parser.add_argument("--return-invocation", required=True)
    parser.add_argument("--device", type=int, default=1)
    parser.add_argument("--maximum-wait", type=float, default=133200)
    parser.add_argument("--poll-seconds", type=float, default=30)
    parser.add_argument("--execute", action="store_true")
    args = parser.parse_args()
    print(run(*(getattr(args, name).resolve() for name in ("preflight", "sources", "returned", "output")),
        return_unit=args.return_unit, return_invocation=args.return_invocation, device=args.device,
        maximum_wait=args.maximum_wait, poll_seconds=args.poll_seconds, execute=args.execute)["status"], flush=True)
