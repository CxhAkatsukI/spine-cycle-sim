"""Freeze the complete four-arm study without replacing earlier evidence."""

import argparse
import json
from pathlib import Path
import shutil

from spine_cycle_sim.experiments.campaign_runtime import atomic_write_json, sha256_file
from ..parallel.delivery import verify_pins
from .analysis import analyze


def package(output, matrix, previous, extraction):
    report = json.loads(matrix.read_text())
    old = json.loads(previous.read_text())
    if report["status"] != "PREDICTION_VALIDATED_NOT_HLS_OR_HARDWARE_ADMISSION":
        raise ValueError("completed prediction report required")
    summary = analyze(report, old)
    if any(report.get(key) != value for key, value in summary.items()):
        raise ValueError("summary differs from complete matrix")
    verify_pins(report["pins"])
    replay = json.loads(extraction.read_text())
    if replay["status"] != "MATCHED_G_DIAGNOSTIC_COMPLETE_NOT_TIMING_ADMISSION" or len(replay["rows"]) != 12:
        raise ValueError("completed extraction regression required")
    cases = {0: "empty", 64: "small", 4096: "large"}
    for row in replay["rows"]:
        matches = [r for r in old["rows"] if r["latency"] == row["latency"] and
                   r["case"] == cases[row["updates"]] and r["arm"] == row["observation"]["arm"]]
        if len(matches) != 1 or matches[0]["observation"] != row["observation"] or \
                matches[0]["state_sha256"] != row["state_sha256"]:
            raise ValueError("extraction changed default state/cycles/traffic")
    for row in report["rows"]:
        state = matrix.parent / f'lat{row["latency"]}_{row["case"]}_{row["arm"]}.u32le'
        if sha256_file(state) != row["state_sha256"]:
            raise ValueError("complete output state changed")
    output.mkdir(parents=True, exist_ok=False)
    entries = []
    sources = [("matrix.json", matrix), ("previous_search.json", previous), ("extraction.json", extraction)]
    for step in report["steps"]:
        for key in ("stdout", "stderr"):
            path = Path(step[key]); sources.append(("raw/" + path.name, path))
    for name, path in sources:
        target = output / name; target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(path, target)
        entries.append({"file": name, "source": str(path), "sha256": sha256_file(target),
                        "bytes": target.stat().st_size})
    index = {"status": "HOT_OWNER_PREDICTION_CHECKPOINT_NOT_BASELINE_ADMISSION",
        "reports": entries, "prediction_rows": len(report["rows"]), **summary,
        "extraction_exact_rows": 12, "baseline_admitted": False,
        "hardware_timing_admitted": False, "publication_match_admitted": False,
        "new_spine_comparison_executed": False}
    atomic_write_json(output / "index.json", index)
    return index


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    for key in ("output", "matrix", "previous", "extraction"):
        parser.add_argument("--" + key, type=Path, required=True)
    args = parser.parse_args()
    result = package(args.output, args.matrix, args.previous, args.extraction)
    print(json.dumps({"status": result["status"], "prediction_rows": result["prediction_rows"]}))
