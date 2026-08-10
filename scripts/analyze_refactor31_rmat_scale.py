#!/usr/bin/env python3
"""Hash-check and summarize the routed refactor31 151M-edge RMAT matrix."""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
from pathlib import Path
import sys
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from spine_cycle_sim.calibration.refactor31_scale import (
    load_refactor31_rmat_runs,
    summarize_refactor31_rmat_runs,
    validate_semantic_comparison,
)


DEFAULT_MANIFEST = ROOT / "configs/evidence/spine_refactor31_rmat_scale_v1.json"


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def write_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--manifest", type=Path, default=DEFAULT_MANIFEST)
    parser.add_argument("--out-dir", type=Path, required=True)
    args = parser.parse_args()
    manifest = json.loads(args.manifest.read_text(encoding="utf-8"))
    artifacts = {item["kind"]: Path(item["path"]) for item in manifest["artifacts"]}
    for item in manifest["artifacts"]:
        path = Path(item["path"])
        if sha256(path) != item["sha256"]:
            raise ValueError(f"artifact hash mismatch: {path}")

    records = load_refactor31_rmat_runs(artifacts["candidate_trials"])
    semantic_rows = validate_semantic_comparison(
        artifacts["semantic_hashes"], artifacts["semantic_mismatches"]
    )
    summaries = summarize_refactor31_rmat_runs(records)
    if len(records) != 1656 or semantic_rows != 1656 or len(summaries) != 48:
        raise ValueError("RMAT matrix shape does not match the frozen protocol")
    if not all(row["repeat_gate"] and row["semantic_ledger_gate"] for row in summaries):
        raise ValueError("RMAT matrix failed repeat or semantic ledger admission")

    output = args.out_dir.resolve()
    output.mkdir(parents=True, exist_ok=True)
    write_csv(output / "refactor31_rmat_group_summary.csv", summaries)
    report = {
        "schema_version": 1,
        "evidence_id": manifest["evidence_id"],
        "manifest_sha256": sha256(args.manifest),
        "graph": "RMat-24 edge-factor-9",
        "graph_edges": 150_994_944,
        "hardware_rows": len(records),
        "measured_rows": sum(not record.warmup for record in records),
        "admitted_rows": sum(record.admitted for record in records),
        "semantic_hash_rows": semantic_rows,
        "group_count": len(summaries),
        "all_groups_admitted": True,
        "update_sizes": [1, 16, 256, 4096],
        "cohorts": sorted({record.cohort for record in records}),
        "state_classes": sorted({record.state_class for record in records}),
        "claim_boundary": {
            "supported": [
                "routed_refactor31_execution_at_150994944_graph_edges",
                "device_status_and_request_ledger_closure",
                "baseline_candidate_exact_semantic_hash_equivalence",
                "repeat_stability_across_update_size_cohort_and_persistent_state",
            ],
            "not_supported": [
                "independent_cpu_dijkstra_correctness",
                "real_graph_slice_transfer",
                "simulator_cycle_error_on_rmat24",
                "paper_owner_scheduler_fpga_calibration",
            ],
        },
    }
    (output / "refactor31_rmat_scale_evidence.json").write_text(
        json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    print(
        f"rows={len(records)} measured={report['measured_rows']} "
        f"groups={len(summaries)} semantic_hashes={semantic_rows} PASS"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
