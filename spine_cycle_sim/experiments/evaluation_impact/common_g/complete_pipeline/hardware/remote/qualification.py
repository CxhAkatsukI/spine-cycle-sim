"""Reuse the production numerical/board validators for an explicitly returned link."""

from functools import partial
import json
import math
from pathlib import Path
import time

from spine_cycle_sim.experiments.campaign_runtime import atomic_write_json
from spine_cycle_sim.experiments.sharded_k4_stages.execution import identity
from spine_cycle_sim.experiments.sharded_k4_stages.row_line.directory_tile.hardware.concurrent import Lease
from spine_cycle_sim.experiments.sharded_k4_stages.row_line.directory_tile.hardware.containment import current, other_builds
from spine_cycle_sim.experiments.upstream_controls.execution import available_memory_bytes
from ....continuous_board.execution import study as board
from ....production_board import experiments
from ....search_pipeline.synthesis import unchanged
from . import admission

PASS = "PRODUCTION_G_GR_BOARD_QUALIFICATION_PASS_NOT_BASELINE_ADMISSION"
POLICY = {"tree_memory_gib": 8, "reserve_gib": 24, "allow_bounded_builds": True}


def run(native_preflight, metadata_preflight, gr_preflight, returned, original, output, *,
        parent_directory, receipt_sha256, device=0, repeats=3, maximum_wait=3600, poll_seconds=30):
    if type(device) is not int or device not in (0, 1) or type(repeats) is not int or not 3 <= repeats <= 10 or any(
            type(value) not in (int, float) or not math.isfinite(value) or value <= 0
            for value in (maximum_wait, poll_seconds)):
        raise ValueError("known board, 3--10 repetitions and bounded memory wait required")
    output.mkdir(parents=True, exist_ok=False)
    report = {"status": "PREPARING", "errors": [], "matrices": [], "board_started": False,
              "board_correctness_measured": False, "device_index": device, "repeats": repeats,
              "policy": POLICY, "maximum_wait_seconds": maximum_wait, "poll_seconds": poll_seconds,
              **dict.fromkeys(board.CLAIMS, False)}
    save = lambda: atomic_write_json(output / "results.json", report)
    lease = None
    save()
    try:
        report["containment"] = board.containment()
        review = partial(admission.review, parent_directory=parent_directory, receipt_sha256=receipt_sha256)
        plans = experiments.plans(native_preflight, metadata_preflight, gr_preflight, route_review=review)
        pins = [identity(path) for path in sorted(Path(__file__).parent.glob("*.py"))]
        for name, preflight, spec, count in plans:
            host, identities = spec.host_identity(preflight)
            if len(host["contract"]["cases"]) != count:
                raise ValueError("production board scope changed: " + name)
            pins += identities
        checked = review(returned, original, output / "routed_admission")
        pins += checked["pins"] + [checked["candidate"], checked["timing"]["report"]]
        report.update(admission=checked, pins=pins)
        unchanged(pins)
        lease = Lease(Path.home() / ".cache/spine-cycle-sim/compiler-reservations", current())
        started = time.monotonic()
        while True:
            unchanged(pins)
            available = available_memory_bytes()
            report["memory_admission"] = lease.sample(available, other_builds(), POLICY,
                                                      commit=available >= 112 * 1024**3)
            report.update(status="WAITING_FOR_SAFE_BOARD_MEMORY", waited_seconds=time.monotonic() - started)
            save()
            if lease.held:
                break
            if report["waited_seconds"] >= maximum_wait:
                raise TimeoutError("board full peer budgets or 104-GiB watchdog reserve do not fit; no board requested")
            time.sleep(min(poll_seconds, maximum_wait - report["waited_seconds"]))
        for name, preflight, spec, count in plans:
            unchanged(pins)
            matrix = {"name": name, "output": str(output / name), "status": "REQUESTED"}
            report["matrices"].append(matrix)
            report["status"] = "RUNNING_" + name
            save()
            result = board.run(preflight, returned, original, output / name, device=device, repeats=repeats,
                               execute=True, experiment=spec)
            matrix.update(status=result["status"], report=identity(output / name / "results.json"))
            report["board_started"] = report["board_started"] or result["board_started"]
            save()
            if result["status"] != spec.pass_status or result["board_correctness_measured"] is not True or \
                    result["board_started"] is not True or len(result["attempts"]) != repeats * count or any(
                        result.get(key) is not False for key in board.CLAIMS):
                raise ValueError("incomplete production board matrix: " + name)
        unchanged(pins)
        report.update(status=PASS, board_correctness_measured=True)
    except BaseException as error:
        for matrix in report["matrices"]:
            child = Path(matrix["output"]) / "results.json"
            if child.is_file():
                try:
                    result = json.loads(child.read_text())
                    matrix.update(status=result["status"], report=identity(child))
                    report["board_started"] = report["board_started"] or result["board_started"]
                except (OSError, ValueError, KeyError, TypeError) as child_error:
                    report["errors"].append("child report unreadable: " + repr(child_error))
        report["status"] = "FAILED_RETAINED"
        report["errors"].append(repr(error))
        raise
    finally:
        if lease is not None:
            lease.release()
        group = report.get("containment", {}).get("path")
        if group:
            report["memory_events_after"] = (Path(group) / "memory.events").read_text()
        save()
    return report
