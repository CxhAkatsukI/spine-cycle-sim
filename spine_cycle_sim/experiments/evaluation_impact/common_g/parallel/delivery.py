"""Freeze complete prediction and synthesis attempts without promoting G."""

import argparse
import json
from pathlib import Path
import shutil

from spine_cycle_sim.experiments.campaign_runtime import atomic_write_json, sha256_file
from .analysis import summarize
from .validation import validate_matrix


def verify_pins(pins):
    for pin in pins:
        if sha256_file(Path(pin["path"])) != pin["sha256"]:
            raise ValueError("frozen evidence changed: " + pin["path"])


def completed_matrix(path, previous):
    report = json.loads(path.read_text())
    if report["status"] != "PREDICTION_AND_SOURCE_HELPERS_PASS_NOT_HARDWARE_ADMISSION":
        raise ValueError("complete candidate prediction report required")
    validate_matrix(report)
    summary = summarize(report["rows"], json.loads(previous.read_text()))
    if any(report.get(key) != value for key, value in summary.items()):
        raise ValueError("candidate summary differs from complete observations")
    verify_pins(report["pins"])
    return report


def synthesis_summary(path):
    report = json.loads(path.read_text())
    if report["status"] != "SYNTHESIZED_REQUIRES_SCHEDULE_REVIEW_AND_RTL_VALIDATION":
        raise ValueError("complete isolated HLS report required")
    if report["hardware_timing_admitted"] is not False or report["production_baseline_admitted"] is not False:
        raise ValueError("isolated HLS is not routed/integrated G admission")
    verify_pins(report["source"] + report["reports"])
    if sha256_file(path.parent / "search.hw.xo") != report["xo_sha256"]:
        raise ValueError("isolated HLS object changed")
    tops = [item for item in report["reports"] if item["path"].endswith("/solution/syn/report/csynth.xml")]
    if not tops or any((item["clock_ns"], item["resources"]) !=
                       (tops[0]["clock_ns"], tops[0]["resources"]) for item in tops):
        raise ValueError("missing or inconsistent top-level HLS report")
    clock = float(tops[0]["clock_ns"])
    if clock <= 0:
        raise ValueError("invalid estimated HLS clock")
    return {"estimated_clock_ns": clock, "target_clock_ns": 5.0,
            "estimated_clock_target_met": clock <= 5.0,
            "resources": {key: int(value) for key, value in tops[0]["resources"].items()},
            "rtl_cosimulation_passed": False, "integrated_or_routed": False}


def package(output, matrix, previous, hls, retained):
    report = completed_matrix(matrix, previous)
    summaries = [synthesis_summary(path) for path in hls]
    for path in retained:
        status = json.loads(path.read_text())["status"]
        if status not in ("FAILED_RETAINED", "PREDICTION_AND_SOURCE_HELPERS_PASS_NOT_HARDWARE_ADMISSION"):
            raise ValueError("running/unknown retained attempt")
    output.mkdir(parents=True, exist_ok=False)
    entries = []
    sources = [("matrix.json", matrix), ("previous_g.json", previous)]
    sources += [(f"hls_{index + 1}.json", path) for index, path in enumerate(hls)]
    sources += [(f"retained_{index + 1}.json", path) for index, path in enumerate(retained)]
    for name, path in sources:
        target = output / name
        shutil.copyfile(path, target)
        entries.append({"file": name, "source": str(path), "sha256": sha256_file(target),
                        "bytes": target.stat().st_size})
    index = {"status": "G_SEARCH_DIAGNOSTIC_PERFORMANCE_AND_HARDWARE_GATES_OPEN",
        "reports": entries, "prediction_rows": len(report["rows"]),
        "default_regression_rows": report["default_regression_rows"],
        "comparisons": report["comparisons"], "synthesis": summaries,
        "prediction_no_more_than_ten_percent_slower": report["prediction_no_more_than_ten_percent_slower"],
        "within_ten_percent_both_directions": report["within_ten_percent_both_directions"],
        "baseline_admitted": False, "hardware_timing_admitted": False,
        "publication_match_admitted": False, "new_spine_comparison_executed": False}
    atomic_write_json(output / "index.json", index)
    return index


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("output", "matrix", "previous"):
        parser.add_argument("--" + name, type=Path, required=True)
    parser.add_argument("--hls", nargs="+", type=Path, required=True)
    parser.add_argument("--retained", nargs="+", type=Path, required=True)
    args = parser.parse_args()
    result = package(args.output, args.matrix, args.previous, args.hls, args.retained)
    print(json.dumps({"status": result["status"], "output": str(args.output)}))
