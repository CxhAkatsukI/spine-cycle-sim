"""Package checked prepared-batch evidence without admitting the baseline."""

import argparse
import json
from pathlib import Path
import shutil
import tarfile

from spine_cycle_sim.experiments.campaign_runtime import atomic_write_json, sha256_file
from ..parallel.delivery import verify_pins
from .analysis import analyze
from .preparation import STATUS


def package(output, matrix, *, status=STATUS, analyze_rows=analyze):
    report = json.loads(matrix.read_text())
    if report["status"] != status or report["errors"]:
        raise ValueError("complete successful sharded-G diagnostic required")
    summary = analyze_rows(report["rows"])
    if any(report.get(key) != value for key, value in summary.items()):
        raise ValueError("summary differs from full sharded-G matrix")
    verify_pins(report["pins"])
    verify_pins(report.get("input_pins", []))
    for row in report["rows"]:
        if sha256_file(Path(row["state_path"])) != row["state_sha256"]:
            raise ValueError("canonical full-state artifact changed")
        verify_pins(row.get("batch_states", []))
    sources = [("input_contract.json", matrix.parent / "input_contract.json")]
    sources.extend((item["member"], Path(item["path"])) for item in report.get("input_pins", []))
    for step in report["steps"]:
        for key in ("stdout", "stderr"):
            path = Path(step[key])
            sources.append(("raw/" + path.name, path))
        path = Path(step["stdout"].replace(".stdout.txt", ".resources.json"))
        sources.append(("raw/" + path.name, path))
    if len({name for name, _ in sources}) != len(sources):
        raise ValueError("ambiguous raw evidence member")
    output.mkdir(parents=True, exist_ok=False)
    target = output / "matrix.json"
    shutil.copyfile(matrix, target)
    members = []
    archive = output / "raw_runs.tar.gz"
    with tarfile.open(archive, "w:gz") as handle:
        for name, path in sources:
            handle.add(path, arcname=name, recursive=False)
            members.append({"member": name, "sha256": sha256_file(path), "bytes": path.stat().st_size})
    index = {"status": status, **summary,
        "new_spine_comparison_executed": False, "raw_members": members,
        "reports": [{"file": p.name, "sha256": sha256_file(p), "bytes": p.stat().st_size}
                    for p in (target, archive)],
        "large_states": "full canonical state hashes in matrix; raw artifacts retained outside Git",
        "canonical_state": "oracle form serialized only after complete physical buffer equality"}
    atomic_write_json(output / "index.json", index)
    return index


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--matrix", required=True, type=Path)
    args = parser.parse_args()
    result = package(args.output.resolve(), args.matrix.resolve())
    print(json.dumps({key: result[key] for key in ("status", "prediction_rows")}))
