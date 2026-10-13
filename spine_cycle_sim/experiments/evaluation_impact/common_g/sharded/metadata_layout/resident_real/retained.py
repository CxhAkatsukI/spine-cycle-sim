"""Preserve failed resident attempts without accepting their partial rows."""

import argparse
import json
from pathlib import Path
import shutil
import tarfile

from spine_cycle_sim.experiments.campaign_runtime import atomic_write_json, sha256_file
from ....parallel.delivery import verify_pins


def package_failure(matrix, output):
    report = json.loads(matrix.read_text())
    if report["status"] != "FAILED_RETAINED" or not report["errors"]:
        raise ValueError("an explicitly failed attempt with retained row errors is required")
    verify_pins(report["pins"])
    output.mkdir(parents=True, exist_ok=False)
    target = output / "matrix.json"
    shutil.copyfile(matrix, target)
    sources = [matrix.parent / "input_contract.json", *sorted((matrix.parent / "raw").glob("*"))]
    archive = output / "raw_runs.tar.gz"
    members = []
    with tarfile.open(archive, "w:gz") as handle:
        for path in sources:
            member = path.relative_to(matrix.parent).as_posix()
            handle.add(path, arcname=member, recursive=False)
            members.append({"member": member, "sha256": sha256_file(path), "bytes": path.stat().st_size})
    atomic_write_json(output / "index.json", {"status": "FAILED_PREFLIGHT_RETAINED",
        "partial_rows": len(report["rows"]), "errors": report["errors"], "accepted_full_matrix_rows": 0,
        "production_baseline_admitted": False, "hardware_timing_admitted": False,
        "publication_match_admitted": False, "raw_members": members,
        "reports": [{"file": p.name, "sha256": sha256_file(p), "bytes": p.stat().st_size}
                    for p in (target, archive)]})


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--matrix", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    package_failure(args.matrix.resolve(), args.output.resolve())
