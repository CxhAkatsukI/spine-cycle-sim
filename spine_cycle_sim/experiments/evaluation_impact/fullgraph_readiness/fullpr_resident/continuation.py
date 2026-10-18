"""Wait for the exact FullPR return, then run its bounded resident protocol."""

import json
from pathlib import Path
import time

from spine_cycle_sim.experiments.campaign_runtime import atomic_write_json
from ...common_g.complete_pipeline.hardware.algorithm_build import follow, local_follow
from ...common_g.continuous_board.execution.supervisor import route_finished, runner_pins, service_state
from .. import board_preparation, board_study, preparation
from ..continuation import validate_service
from . import gr, gr_preparation, inputs


def run(preflight, returned, admission, output, *, unit, invocation, preflight_sha256,
        device=1, maximum_wait=133200, poll_seconds=30):
    validate_service(unit, invocation)
    if admission != returned / "admission/summary.json" or \
            any(not path.is_absolute() or ".." in path.parts for path in (preflight, returned, admission, output)) or \
            type(device) is not int or device not in (0, 1) or \
            type(maximum_wait) is not int or not 1 <= maximum_wait <= 133200 or \
            type(poll_seconds) is not int or not 1 <= poll_seconds <= 300:
        raise ValueError("exact absolute FullPR paths, known card and bounded wait required")
    output.mkdir(parents=True, exist_ok=False)
    report = {"status": "PREPARING", "errors": [], "states": [], "board_requested": False,
              "hardware_convergence_measured": False, "spine_comparison": False,
              "publication_match": False, "production_baseline_admitted": False,
              "unit": unit, "invocation": invocation, "preflight_sha256": preflight_sha256,
              "returned": str(returned), "admission": str(admission), "device_index": device,
              "maximum_wait_seconds": maximum_wait}
    save = lambda: atomic_write_json(output / "results.json", report)
    save()
    try:
        preflight_pin = preparation.identity(preflight / "results.json")
        if preflight_pin["sha256"] != preflight_sha256:
            raise ValueError("FullPR offline report SHA-256 differs")
        offline = json.loads((preflight / "results.json").read_text())
        report["offline_replay"] = gr_preparation.replay(offline, preflight)
        pins = board_preparation.stamp_pins([preflight_pin, *offline["pins"], *runner_pins()])
        report["pins"] = pins
        preparation.unchanged(pins, full=True)
        started = time.monotonic()
        while True:
            preparation.unchanged(pins)
            state = service_state(unit)
            if not report["states"] or report["states"][-1] != state:
                report["states"].append(state)
            report.update(status="WAITING_FOR_EXACT_FULLPR_RETURN", waited_seconds=time.monotonic() - started)
            save()
            if route_finished(state, invocation):
                break
            if report["waited_seconds"] >= maximum_wait:
                raise TimeoutError("exact FullPR return did not finish within the declared wait")
            time.sleep(min(poll_seconds, maximum_wait - report["waited_seconds"]))
        path = returned / "results.json"
        result = json.loads(path.read_text())
        if result.get("status") not in (follow.PASS, local_follow.PASS) or \
                result.get("algorithm") != inputs.ALGORITHM or \
                result.get("errors") != [] or result.get("board_requested") is not False or \
                result.get("admission") != preparation.identity(admission):
            raise ValueError("exact successful FullPR return/admission required")
        pins += board_preparation.stamp_pins([preparation.identity(path), preparation.identity(admission)])
        preparation.unchanged(pins, full=True)
        report.update(status="RUNNING_FULLPR_BOARD_PROTOCOL", board_requested=True)
        save()
        child = board_study.run(preflight, admission, inputs.ALGORITHM, output / "board",
                                device=device, repeats=3, execute=True, experiment=gr.experiment())
        report["board_report"] = preparation.identity(output / "board/results.json")
        preparation.unchanged(pins, full=True)
        if not route_finished(service_state(unit), invocation) or child.get("status") != gr.PASS or \
                child.get("hardware_convergence_measured") is not True:
            raise ValueError("FullPR producer changed or board protocol did not complete")
        report.update(status=gr.PASS, hardware_convergence_measured=True)
    except BaseException as error:
        report["status"] = "FAILED_RETAINED"
        report["errors"].append(repr(error))
        child_path = output / "board/results.json"
        if child_path.is_file():
            report["board_report"] = preparation.identity(child_path)
        raise
    finally:
        save()
    return report


def main(argv=None):
    import argparse
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("preflight", "returned", "admission", "output"):
        parser.add_argument("--" + name, type=Path, required=True)
    for name in ("unit", "invocation", "preflight-sha256"):
        parser.add_argument("--" + name, required=True)
    parser.add_argument("--device", type=int, default=1)
    args = parser.parse_args(argv)
    print(run(args.preflight.resolve(), args.returned.resolve(), args.admission.resolve(), args.output.resolve(),
              unit=args.unit, invocation=args.invocation, preflight_sha256=args.preflight_sha256,
              device=args.device)["status"], flush=True)


if __name__ == "__main__":
    main()
