"""Wait for bounded campaigns, then export a complete or explicitly partial handoff."""

import argparse
import json
from pathlib import Path
import time

from ...original_regraph_execution.hardware.source_retention.runtime import identity, save
from . import analyze, plot


TERMINAL = {"COMPLETED", "FAILED_RETAINED"}


def completion(campaigns):
    studies = []
    for path in campaigns:
        document = json.loads(path.read_text())
        manifest = json.loads(Path(document["workloads"]["path"]).read_text())
        measured = {row["name"] for row in document["cases"] if row["status"] == "MEASURED"}
        missing = [row["name"] for row in manifest["points"] if row["name"] not in measured]
        studies.append(dict(campaign=identity(path), algorithm=manifest["algorithm"],
                            dataset=manifest["dataset"], status=document["status"],
                            planned_points=len(manifest["points"]), measured_points=len(measured),
                            missing_points=missing))
    return dict(status="COMPLETED" if all(row["status"] == "COMPLETED" and not row["missing_points"]
                                        for row in studies) else "PARTIAL_RETAINED", studies=studies)


def deliver(campaigns, retained, output, *, hardware, candidates=(), wait_seconds=14400):
    deadline = time.monotonic() + wait_seconds
    while any(json.loads(path.read_text())["status"] not in TERMINAL for path in campaigns):
        if time.monotonic() >= deadline:
            output.mkdir(parents=True, exist_ok=False)
            result = completion(campaigns)
            result.update(status="WAIT_TIMEOUT", error="active campaigns were not exported")
            save(output / "delivery.json", result)
            return result
        time.sleep(min(10, max(0, deadline - time.monotonic())))
    result = completion(campaigns)
    output.mkdir(parents=True, exist_ok=False)
    summary = analyze.export([*campaigns, *retained], output / "data")
    plot.render(output / "data" / "summary.json", output / "figures" / "crossover")
    result.update(measured_points=summary["measured_points"], total_samples=summary["total_samples"],
                  hardware=identity(hardware), exporter=identity(__file__),
                  retained_campaigns=[identity(path) for path in retained], candidates=[])
    save(output / "data" / "hardware.json", json.loads(hardware.read_text()))
    for index, path in enumerate(candidates):
        result["candidates"].append(identity(path))
        save(output / "data" / f"cpu-candidates-{index}.json", json.loads(path.read_text()))
    result["files"] = {str(path.relative_to(output)): identity(path)
                       for path in sorted(output.rglob("*")) if path.is_file()}
    save(output / "delivery.json", result)
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--campaign", type=Path, action="append", required=True)
    parser.add_argument("--retained-campaign", type=Path, action="append", default=[])
    parser.add_argument("--candidate", type=Path, action="append", default=[])
    parser.add_argument("--hardware", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--wait-seconds", type=int, default=14400)
    args = parser.parse_args()
    if args.wait_seconds < 0:
        parser.error("wait time must be nonnegative")
    result = deliver(args.campaign, args.retained_campaign, args.output,
                     hardware=args.hardware, candidates=args.candidate, wait_seconds=args.wait_seconds)
    print(result["status"], result["measured_points"], "points;", result["total_samples"], "samples")


if __name__ == "__main__":
    main()
