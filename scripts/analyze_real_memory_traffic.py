#!/usr/bin/env python3
"""Create common real-compact memory traffic and locality evidence."""

from __future__ import annotations

import argparse
import csv
import json
from pathlib import Path
import sys


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from spine_cycle_sim.experiments.real_memory_analysis import (  # noqa: E402
    load_matrix,
    pair_memory_rows,
    sha256_file,
    summarize_pairs,
)


def _write_csv(path: Path, rows: list[dict[str, object]]) -> None:
    if not rows:
        raise ValueError("cannot write an empty CSV")
    fields: list[str] = []
    seen: set[str] = set()
    for row in rows:
        for key in row:
            if key not in seen:
                seen.add(key)
                fields.append(key)
    with path.open("w", encoding="utf-8", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=fields, lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)


def _evidence_path(path: Path) -> str:
    resolved = path.resolve()
    try:
        return str(resolved.relative_to(ROOT.resolve()))
    except ValueError:
        return str(resolved)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--weighted-dir", type=Path, required=True)
    parser.add_argument("--full-pagerank-dir", type=Path, required=True)
    parser.add_argument("--residual-pagerank-dir", type=Path, required=True)
    parser.add_argument("--out-dir", type=Path, required=True)
    args = parser.parse_args()

    inputs = (
        ("weighted_sssp", args.weighted_dir),
        ("full_pagerank", args.full_pagerank_dir),
        ("thresholded_residual_pagerank", args.residual_pagerank_dir),
    )
    manifests: dict[str, dict[str, object]] = {}
    rows: list[dict[str, object]] = []
    for algorithm, directory in inputs:
        manifest, matrix_rows = load_matrix(algorithm, directory)
        manifests[algorithm] = manifest
        rows.extend(matrix_rows)
    pairs = pair_memory_rows(rows)
    summaries = summarize_pairs(pairs)

    args.out_dir.mkdir(parents=True, exist_ok=True)
    system_path = args.out_dir / "memory_system_rows.csv"
    pair_path = args.out_dir / "memory_pairs.csv"
    summary_path = args.out_dir / "memory_group_summary.csv"
    _write_csv(system_path, rows)
    _write_csv(pair_path, pairs)
    _write_csv(summary_path, summaries)
    evidence = {
        "schema_version": 1,
        "evidence_id": "real_compact_memory_traffic_locality_20260726",
        "status": "PASS",
        "claim_class": "accepted_backend_request_trace_locality",
        "classification": (
            "per_initiator_and_operation_accepted_backend_request"
        ),
        "address_basis": "logical_channel_and_byte_address",
        "algorithms": list(manifests),
        "system_rows": len(rows),
        "pairs": len(pairs),
        "all_input_matrices_correct": all(
            manifest["all_correct"] is True for manifest in manifests.values()
        ),
        "analysis_sources": {
            "runner": {
                "path": _evidence_path(Path(__file__)),
                "sha256": sha256_file(Path(__file__)),
            },
            "model": {
                "path": "spine_cycle_sim/experiments/real_memory_analysis.py",
                "sha256": sha256_file(
                    ROOT
                    / "spine_cycle_sim"
                    / "experiments"
                    / "real_memory_analysis.py"
                ),
            },
        },
        "input_matrices": {
            algorithm: {
                "directory": _evidence_path(directory),
                "manifest_sha256": sha256_file(directory / "matrix_manifest.json"),
                "execution_sha256": manifests[algorithm]["execution_sha256"],
            }
            for algorithm, directory in inputs
        },
        "outputs": {
            "memory_system_rows_sha256": sha256_file(system_path),
            "memory_pairs_sha256": sha256_file(pair_path),
            "memory_group_summary_sha256": sha256_file(summary_path),
        },
        "summaries": summaries,
        "limitations": [
            (
                "Contiguous, repeated, and discontinuous classify accepted "
                "logical backend requests; they do not identify DRAM row hits."
            ),
            (
                "Requested bytes exclude controller burst amplification and "
                "are distinct from physical HBM transfer bytes."
            ),
            (
                "Weighted Spine currently exposes cold versus aligned E2E "
                "traffic, not an internal maintenance-versus-compute split."
            ),
            "Inputs are compact real-edge slices, not full datasets.",
        ],
    }
    evidence_path = args.out_dir / "memory_evidence.json"
    evidence_path.write_text(
        json.dumps(evidence, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    print(
        f"PASS memory traffic analysis: rows={len(rows)} pairs={len(pairs)} "
        f"algorithms={len(manifests)}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
