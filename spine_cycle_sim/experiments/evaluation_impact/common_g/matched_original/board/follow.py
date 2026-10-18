"""Run the matched-input G matrix after one exact production board qualifier."""

import argparse
import json
from pathlib import Path
import re
import time

from spine_cycle_sim.experiments.campaign_runtime import atomic_write_json
from spine_cycle_sim.experiments.sharded_k4_stages.execution import identity
from spine_cycle_sim.experiments.sharded_k4_stages.row_line.directory_tile.hardware.containment import current, verify
from ...complete_pipeline.hardware.remote import qualification
from ...continuous_board.execution.supervisor import route_finished, runner_pins, service_state
from ...search_pipeline.synthesis import unchanged
from ..analysis import CLAIMS
from . import execution, inputs


def run(preflight, original_preflight, producer, parent, original, output, *, unit, invocation,
        device=0, repeats=3, maximum_wait=133200, poll_seconds=30, preflight_sha256=inputs.PREFLIGHT_SHA256,
        original_preflight_sha256=inputs.ORIGINAL_PREFLIGHT_SHA256):
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.@:-]*\.service", unit) or \
            not re.fullmatch(r"[0-9a-f]{32}", invocation) or type(maximum_wait) is not int or \
            not 1 <= maximum_wait <= 133200 or type(poll_seconds) is not int or not 1 <= poll_seconds <= 300 or \
            type(device) is not int or device not in (0, 1) or type(repeats) is not int or not 3 <= repeats <= 10:
        raise ValueError("exact producer service, finite wait, known device and repeated matrix required")
    output.mkdir(parents=True, exist_ok=False)
    report = {"status": "PREPARING", "errors": [], "states": [], "unit": unit, "invocation": invocation,
              "producer_directory": str(producer), "maximum_wait_seconds": maximum_wait,
              "device_index": device, "repeats": repeats, "board_launch_attempted": False,
              **dict.fromkeys(CLAIMS, False)}
    save = lambda: atomic_write_json(output / "results.json", report)
    save()
    try:
        report["containment"] = verify(current(), memory_gib=4)
        _, cases, pins = inputs.load(preflight, original_preflight, preflight_sha256=preflight_sha256,
                                    original_preflight_sha256=original_preflight_sha256)
        if len(cases) != 8:
            raise ValueError("all eight original G inputs required")
        manifest = json.loads((parent / "manifest.json").read_text())
        pins += [identity(parent / "manifest.json"), identity(original), *manifest["pins"], *runner_pins()]
        report["pins"] = pins
        started = time.monotonic()
        while True:
            unchanged(pins)
            state = service_state(unit)
            if not report["states"] or report["states"][-1] != state:
                report["states"].append(state)
            report.update(status="WAITING_FOR_EXACT_PRODUCTION_QUALIFIER",
                          waited_seconds=time.monotonic() - started)
            save()
            if route_finished(state, invocation):
                break
            if report["waited_seconds"] >= maximum_wait:
                raise TimeoutError("production qualifier did not finish; no matched-G device requested")
            time.sleep(min(poll_seconds, maximum_wait - report["waited_seconds"]))
        child_path = producer / "results.json"
        captured = identity(child_path)
        child = json.loads(child_path.read_text())
        if child.get("status") != qualification.PASS or child.get("board_correctness_measured") is not True or \
                child.get("board_started") is not True or child.get("errors") != [] or \
                child.get("device_index") != device or not re.fullmatch(
                    r"[0-9a-f]{64}", child.get("receipt_sha256", "")):
            raise ValueError("exact producer lacks successful production board qualification")
        pins.append(captured)
        report.update(producer_report=captured, receipt_sha256=child["receipt_sha256"],
                      status="RUNNING_MATCHED_G_MATRIX")
        save()
        unchanged(pins)
        if not route_finished(service_state(unit), invocation):
            raise ValueError("production qualifier invocation changed")
        result = execution.run(preflight, original_preflight, producer / "returned", parent, original,
            output / "board", receipt_sha256=child["receipt_sha256"], device=device, repeats=repeats,
            preflight_sha256=preflight_sha256, original_preflight_sha256=original_preflight_sha256)
        if result["status"] != execution.PASS or result["hardware_timing_measured"] is not True or \
                result["board_launch_attempted"] is not True or len(result["rows"]) != 8 * repeats:
            raise ValueError("matched-G matrix did not complete")
        unchanged(pins)
        report.update(status=execution.PASS, hardware_timing_measured=True, board_launch_attempted=True,
                      board_report=identity(output / "board/results.json"))
    except BaseException as error:
        path = output / "board/results.json"
        if path.is_file():
            try:
                child = json.loads(path.read_text())
                report.update(board_launch_attempted=child["board_launch_attempted"], board_report=identity(path))
            except (OSError, ValueError, KeyError, TypeError) as child_error:
                report["errors"].append("child report unreadable: " + repr(child_error))
        report["status"] = "FAILED_RETAINED"
        report["errors"].append(repr(error))
        raise
    finally:
        save()
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("preflight", "original-preflight", "producer", "parent", "original", "output"):
        parser.add_argument("--" + name, type=Path, required=True)
    for name in ("unit", "invocation"):
        parser.add_argument("--" + name, required=True)
    parser.add_argument("--preflight-sha256", default=inputs.PREFLIGHT_SHA256)
    parser.add_argument("--original-preflight-sha256", default=inputs.ORIGINAL_PREFLIGHT_SHA256)
    parser.add_argument("--device", type=int, default=0)
    parser.add_argument("--repeats", type=int, default=3)
    parser.add_argument("--maximum-wait", type=int, default=133200)
    parser.add_argument("--execute", action="store_true", required=True)
    args = vars(parser.parse_args())
    args.pop("execute")
    args = {key: value.resolve() if isinstance(value, Path) else value for key, value in args.items()}
    print(run(**args)["status"], flush=True)


if __name__ == "__main__":
    main()
