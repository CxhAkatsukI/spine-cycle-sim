"""Package complete cached-G predictions without claiming timing admission."""

import argparse
import json
from pathlib import Path
import shutil
import tarfile

from spine_cycle_sim.experiments.campaign_runtime import atomic_write_json, sha256_file
from ..parallel.delivery import verify_pins
from .analysis import analyze


def package(output, matrix, previous):
    report = json.loads(matrix.read_text())
    if report["status"] != "CACHED_G_PREDICTION_VALIDATED_REFERENCE_TIMING_OPEN":
        raise ValueError("complete cached-G prediction required")
    summary = analyze(report, json.loads(previous.read_text()))
    if any(report.get(key) != value for key, value in summary.items()):
        raise ValueError("cached-G summary differs from full matrix")
    verify_pins(report["pins"])
    for row in report["rows"]:
        state = matrix.parent / f'lat{row["latency"]}_{row["case"]}_{row["arm"]}.u32le'
        if sha256_file(state) != row["state_sha256"]:
            raise ValueError("complete cached-G output state changed")
    sources = [("matrix.json", matrix), ("previous_hot_owners.json", previous)]
    raw_sources = []
    for step in report["steps"]:
        for key in ("stdout", "stderr"):
            path = Path(step[key])
            raw_sources.append((path.name, path))
        resources = Path(step["stdout"].replace(".stdout.txt", ".resources.json"))
        raw_sources.append((resources.name, resources))
    if len({name for name, _ in raw_sources}) != len(raw_sources):
        raise ValueError("ambiguous cached-G evidence names")
    output.mkdir(parents=True, exist_ok=False)
    entries = []
    for name, path in sources:
        target = output / name
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(path, target)
        entries.append({"file": name, "source": str(path), "sha256": sha256_file(target),
                        "bytes": target.stat().st_size})
    raw_members = []
    archive = output / "raw_runs.tar.gz"
    with tarfile.open(archive, "w:gz") as handle:
        for name, path in raw_sources:
            handle.add(path, arcname=name, recursive=False)
            raw_members.append({"member": name, "source": str(path),
                                "sha256": sha256_file(path), "bytes": path.stat().st_size})
    entries.append({"file": archive.name, "sha256": sha256_file(archive),
                    "bytes": archive.stat().st_size})
    index = {"status": "CACHED_G_PREDICTION_CHECKPOINT_REFERENCE_TIMING_OPEN",
        "reports": entries, "raw_members": raw_members,
        "prediction_rows": len(report["rows"]), **summary,
        "baseline_admitted": False, "hardware_timing_admitted": False,
        "publication_match_admitted": False, "reference_cache_timing_admitted": False,
        "new_spine_comparison_executed": False}
    atomic_write_json(output / "index.json", index)
    return index


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    for key in ("output", "matrix", "previous"):
        parser.add_argument("--" + key, type=Path, required=True)
    args = parser.parse_args()
    result = package(args.output, args.matrix, args.previous)
    print(json.dumps({"status": result["status"], "prediction_rows": result["prediction_rows"]}))
