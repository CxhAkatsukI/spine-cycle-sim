"""Wait for bounded campaigns, then export a complete or explicitly partial handoff."""

import argparse
import json
from pathlib import Path
import time

from ...original_regraph_execution.hardware.source_retention.runtime import identity, save
from . import analyze, plot


TERMINAL = {"COMPLETED", "COMPLETED_WITH_FAILURES", "FAILED_RETAINED"}


def completion(campaigns):
    studies, expected, attempted, failed = [], set(), set(), []
    for path in campaigns:
        document = json.loads(path.read_text())
        manifest = json.loads(Path(document["workloads"]["path"]).read_text())
        group = (manifest["algorithm"], manifest["dataset"])
        expected.update((*group, row["name"]) for row in manifest["points"])
        for row in document["cases"]:
            key = (*group, row["name"])
            if key in attempted:
                raise ValueError("duplicate primary attempt: " + repr(key))
            if row["status"] == "MEASURED":
                attempted.add(key)
            elif (row["status"] == "FAILED_RETAINED" and row.get("samples")
                  and row["samples"][-1].get("status") == "FAILED_RETAINED"):
                attempted.add(key)
                failed.append(dict(algorithm=group[0], dataset=group[1], name=row["name"]))
        measured = {row["name"] for row in document["cases"] if row["status"] == "MEASURED"}
        studies.append(dict(campaign=identity(path), algorithm=manifest["algorithm"],
                            dataset=manifest["dataset"], status=document["status"],
                            planned_points=len(manifest["points"]), measured_points=len(measured),
                            planned_names=[row["name"] for row in manifest["points"]]))
    if attempted - expected:
        raise ValueError("attempted point was not planned")
    for study in studies:
        study["missing_points"] = [name for name in study["planned_names"]
                                   if (study["algorithm"], study["dataset"], name) not in attempted]
    complete = expected == attempted and all(row["status"] in TERMINAL for row in studies)
    status = ("COMPLETED_WITH_FAILURES" if failed else "COMPLETED") if complete else "PARTIAL_RETAINED"
    return dict(status=status, studies=studies, planned_unique_points=len(expected), failed_points=failed)


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
