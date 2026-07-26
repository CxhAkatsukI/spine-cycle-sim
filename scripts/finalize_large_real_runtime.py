#!/usr/bin/env python3
"""Finalize a completed large-real run without launching another simulation."""

from __future__ import annotations

import argparse
import csv
import json
from pathlib import Path
import sys


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from spine_cycle_sim.experiments.large_real_pagerank import (  # noqa: E402
    build_large_real_runtime_acceptance,
    validate_large_real_pagerank_manifest,
)
from spine_cycle_sim.experiments.shared_workloads import sha256_file  # noqa: E402


def _read_csv(path: Path) -> list[dict[str, str]]:
    if not path.is_file():
        raise ValueError(f"missing result table: {path}")
    with path.open("r", encoding="utf-8", newline="") as stream:
        rows = list(csv.DictReader(stream))
    if not rows:
        raise ValueError(f"empty result table: {path}")
    return rows


def _resolve_result_path(value: object) -> Path:
    if not isinstance(value, str) or not value:
        raise ValueError("raw result path is missing")
    path = Path(value)
    return path if path.is_absolute() else ROOT / path


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--result-dir", type=Path, required=True)
    parser.add_argument("--out", type=Path)
    args = parser.parse_args()

    result_dir = args.result_dir.resolve()
    matrix_path = result_dir / "matrix_manifest.json"
    system_path = result_dir / "system_rows.csv"
    pairs_path = result_dir / "pairs.csv"
    if not matrix_path.is_file():
        raise ValueError(f"missing matrix manifest: {matrix_path}")
    matrix = json.loads(matrix_path.read_text(encoding="utf-8"))
    input_path = Path(str(matrix.get("input_manifest", ""))).resolve()
    manifest = validate_large_real_pagerank_manifest(ROOT, input_path)

    expected_input_sha = matrix.get("input_manifest_sha256")
    if sha256_file(input_path) != expected_input_sha:
        raise ValueError("large-real input manifest hash mismatch")
    for path, field in (
        (system_path, "system_rows_sha256"),
        (pairs_path, "pairs_sha256"),
    ):
        if sha256_file(path) != matrix.get(field):
            raise ValueError(f"large-real result hash mismatch: {path}")

    system_rows = _read_csv(system_path)
    pair_rows = _read_csv(pairs_path)
    raw_results = []
    for row in system_rows:
        raw_path = _resolve_result_path(row.get("raw_result_path"))
        expected_sha = row.get("raw_result_sha256")
        if not raw_path.is_file() or sha256_file(raw_path) != expected_sha:
            raise ValueError(f"large-real raw result hash mismatch: {raw_path}")
        raw_results.append(
            {
                "run_id": row["run_id"],
                "system": row["system"],
                "path": str(raw_path),
                "sha256": expected_sha,
            }
        )

    acceptance = build_large_real_runtime_acceptance(
        manifest, matrix, system_rows, pair_rows
    )
    acceptance["evidence"] = {
        "matrix_manifest": {
            "path": str(matrix_path),
            "sha256": sha256_file(matrix_path),
        },
        "system_rows": {"path": str(system_path), "sha256": sha256_file(system_path)},
        "pairs": {"path": str(pairs_path), "sha256": sha256_file(pairs_path)},
        "raw_results": raw_results,
    }
    output_path = (args.out or result_dir / "runtime_acceptance.json").resolve()
    output_path.write_text(
        json.dumps(acceptance, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    print(f"{acceptance['status']}: {output_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
