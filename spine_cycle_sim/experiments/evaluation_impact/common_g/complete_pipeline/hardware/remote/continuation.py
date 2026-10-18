"""Wait for one remote invocation, then return, admit and qualify its artifact."""

from dataclasses import asdict
import json
import math
from pathlib import Path
import time

from spine_cycle_sim.experiments.campaign_runtime import atomic_write_json
from spine_cycle_sim.experiments.sharded_k4_stages.execution import identity
from ....continuous_board.execution.supervisor import route_finished, runner_pins
from ....production_board import experiments
from ....production_board import route as production
from ....search_pipeline.synthesis import unchanged
from . import capsule, delivery, qualification


def run(remote, native_preflight, metadata_preflight, gr_preflight, parent, original, output, *,
        device=0, repeats=3, maximum_wait=133200, poll_seconds=30):
    if type(device) is not int or device not in (0, 1) or type(repeats) is not int or not 3 <= repeats <= 10 or any(
            type(value) not in (int, float) or not math.isfinite(value) or value <= 0
            for value in (maximum_wait, poll_seconds)):
        raise ValueError("known board, 3--10 repetitions and finite positive wait required")
    output.mkdir(parents=True, exist_ok=False)
    report = {"status": "PREPARING", "errors": [], "remote": {key: str(value) if isinstance(value, Path) else value
              for key, value in asdict(remote).items()}, "states": [], "board_started": False,
              "board_correctness_measured": False, "device_index": device, "repeats": repeats,
              "maximum_wait_seconds": maximum_wait, "poll_seconds": poll_seconds,
              **dict.fromkeys(capsule.FLAGS, False)}
    save = lambda: atomic_write_json(output / "results.json", report)
    save()
    try:
        report["containment"] = qualification.board.containment()
        manifest = json.loads((parent / "manifest.json").read_text())
        production.candidate(manifest)
        pins = [identity(parent / "manifest.json"), identity(original), *manifest["pins"], *runner_pins()]
        for name, preflight, spec, count in experiments.plans(native_preflight, metadata_preflight, gr_preflight):
            host, host_pins = spec.host_identity(preflight)
            if len(host["contract"]["cases"]) != count:
                raise ValueError("production host scope changed: " + name)
            pins += host_pins
        report["pins"] = list({pin["path"]: pin for pin in pins}.values())
        started = time.monotonic()
        while True:
            unchanged(report["pins"])
            state = remote.state()
            if not report["states"] or report["states"][-1] != state:
                report["states"].append(state)
            report.update(status="WAITING_FOR_EXACT_REMOTE_ROUTE", waited_seconds=time.monotonic() - started)
            save()
            if route_finished(state, remote.invocation):
                break
            if report["waited_seconds"] >= maximum_wait:
                raise TimeoutError("remote route did not finish; no board requested")
            time.sleep(min(poll_seconds, maximum_wait - report["waited_seconds"]))
        report["status"] = "SEALING_REMOTE_RETURN"
        save()
        report["receipt_sha256"] = remote.seal()
        save()
        remote.transfer(output / "returned")
        delivery.verify(output / "returned", report["receipt_sha256"])
        unchanged(report["pins"])
        if not route_finished(remote.state(), remote.invocation):
            raise ValueError("remote prerequisite changed after transport")
        report["status"] = "QUALIFYING_RETURNED_ARTIFACT"
        save()
        result = qualification.run(native_preflight, metadata_preflight, gr_preflight, output / "returned",
            original, output / "board", parent_directory=parent, receipt_sha256=report["receipt_sha256"],
            device=device, repeats=repeats)
        unchanged(report["pins"])
        if result["status"] != qualification.PASS or result["board_correctness_measured"] is not True:
            raise ValueError("remote production board qualification incomplete")
        report.update(status=qualification.PASS, board_started=result["board_started"],
                      board_correctness_measured=True, board_report=identity(output / "board/results.json"))
    except BaseException as error:
        child = output / "board/results.json"
        if child.is_file():
            try:
                result = json.loads(child.read_text())
                report.update(board_started=result["board_started"], board_report=identity(child))
            except (OSError, ValueError, KeyError, TypeError) as child_error:
                report["errors"].append("child report unreadable: " + repr(child_error))
        report.update(status="FAILED_RETAINED")
        report["errors"].append(repr(error))
        raise
    finally:
        save()
    return report
