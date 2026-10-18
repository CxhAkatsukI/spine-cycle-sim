"""Wait for an exact board producer, then replay the six complete matrices."""

import json
from pathlib import Path
import time

from spine_cycle_sim.experiments.campaign_runtime import atomic_write_json
from ...common_g.continuous_board.execution.supervisor import route_finished, runner_pins, service_state
from .. import board_study, continuation as producer, preparation
from . import analysis, study


def completed(preflight_pin, source, rows):
    path = source / "results.json"
    pin = preparation.identity(path)
    report = json.loads(path.read_text())
    preparation.unchanged([pin], full=True)
    if report.get("status") != producer.PASS or report.get("errors") != [] or \
            report.get("hardware_convergence_measured") is not True or report.get("board_requested") is not True or \
            report.get("preflight") != preflight_pin or any(report.get(key) is not False for key in (
                "production_baseline_admitted", "spine_comparison", "publication_match")):
        raise ValueError("complete exact producer and offline prerequisite required")
    requests, matrices = report["requests"], report["matrices"]
    expected = sorted(preparation.ALGORITHMS)
    if len(requests) != 3 or len(matrices) != 3 or \
            sorted(item["algorithm"] for item in requests) != expected or \
            sorted(item["algorithm"] for item in matrices) != expected:
        raise ValueError("complete distinct three-algorithm producer required")
    pins = [pin, *report["pins"]]
    for row in rows:
        algorithm = row["algorithm"]
        request = next(item for item in requests if item["algorithm"] == algorithm)
        matrix = next(item for item in matrices if item["algorithm"] == algorithm)
        output = source / algorithm
        if row["gr"] != {"report": str(output / "results.json"), "admission": request["admission"]} or \
                matrix["status"] != board_study.PASS or matrix["output"] != str(output) or \
                matrix["report"] != preparation.identity(output / "results.json"):
            raise ValueError("paired G+R request differs from the exact producer child/admission")
        pins.append(matrix["report"])
    preparation.unchanged(pins, full=True)
    return pins


def run(preflight, request_path, source, output, *, producer_unit, producer_invocation,
        maximum_wait=172800, poll_seconds=30):
    producer.validate_service(producer_unit, producer_invocation)
    if type(maximum_wait) is not int or not 1 <= maximum_wait <= 172800 or \
            type(poll_seconds) is not int or not 1 <= poll_seconds <= 300:
        raise ValueError("bounded producer wait and poll interval required")
    if any(not path.is_absolute() or ".." in path.parts for path in (preflight, request_path, source, output)):
        raise ValueError("absolute canonical evidence paths required")
    output.mkdir(parents=True, exist_ok=False)
    report = {"status": "WAITING_FOR_COMPLETE_BOARD_PRODUCER", "errors": [],
              "producer_unit": producer_unit, "producer_invocation": producer_invocation,
              "producer_output": str(source), "producer_exit_attested": False,
              "board_requested": False, "final_figures_admitted": False,
              "publication_match": False, "production_baseline_admitted": False,
              "maximum_wait_seconds": maximum_wait, "poll_seconds": poll_seconds, "states": []}
    save = lambda: atomic_write_json(output / "results.json", report)
    save()
    try:
        pins = [preparation.identity(request_path), preparation.identity(preflight / "results.json"),
                *[preparation.identity(Path(pin["path"])) for pin in runner_pins()]]
        rows = study.requests(request_path)
        for row in rows:
            if row["gr"]["report"] != str(source / row["algorithm"] / "results.json"):
                raise ValueError("G+R matrix must belong to the declared producer output")
            pins += [preparation.identity(Path(row["spine"][key])) for key in ("report", "admission")]
        report["pins"] = pins
        preparation.unchanged(pins, full=True)
        started = time.monotonic()
        while True:
            preparation.unchanged(pins)
            state = service_state(producer_unit)
            if not report["states"] or report["states"][-1] != state:
                report["states"].append(state)
            report["waited_seconds"] = time.monotonic() - started
            save()
            if route_finished(state, producer_invocation):
                break
            if report["waited_seconds"] >= maximum_wait:
                raise TimeoutError("required board producer wait expired; no paired replay")
            time.sleep(min(poll_seconds, maximum_wait - report["waited_seconds"]))
        pins += completed(pins[1], source, rows)
        report.update(status="REPLAYING_COMPLETE_PAIRED_MATRICES", producer_exit_attested=True)
        save()
        child = study.run(preflight, request_path, output / "paired_replay")
        preparation.unchanged(pins, full=True)
        if not route_finished(service_state(producer_unit), producer_invocation):
            raise ValueError("producer is no longer terminal after replay")
        if child["status"] != analysis.PASS or child.get("errors") != [] or \
                child.get("final_figures_admitted") is not False or len(child["rows"]) != 24:
            raise ValueError("complete offline paired replay required")
        report.update(status=analysis.PASS, paired_report=preparation.identity(output / "paired_replay/results.json"))
    except BaseException as error:
        report["status"] = "FAILED_RETAINED"
        report["errors"].append(repr(error))
        raise
    finally:
        save()
    return report


def main(argv=None):
    import argparse
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("preflight", "requests", "producer-output", "output"):
        parser.add_argument("--" + name, type=Path, required=True)
    for name in ("producer-unit", "producer-invocation"):
        parser.add_argument("--" + name, required=True)
    parser.add_argument("--maximum-wait", type=int, default=172800)
    parser.add_argument("--poll-seconds", type=int, default=30)
    args = parser.parse_args(argv)
    result = run(args.preflight.resolve(), args.requests.resolve(), args.producer_output.resolve(),
                 args.output.resolve(), producer_unit=args.producer_unit,
                 producer_invocation=args.producer_invocation, maximum_wait=args.maximum_wait,
                 poll_seconds=args.poll_seconds)
    print(result["status"], flush=True)


if __name__ == "__main__":
    main()
