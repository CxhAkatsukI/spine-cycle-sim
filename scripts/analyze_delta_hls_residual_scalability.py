#!/usr/bin/env python3
"""Check and summarize Delta.hls residual K=1/direct-K4/shared-K4 evidence."""

from __future__ import annotations

import argparse
import csv
import json
import math
from pathlib import Path
from typing import Any, Mapping


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_INPUTS = {
    "spine": ROOT / "evidence/deltahls_residual_p4_spine_v1/summary.json",
    "k1": ROOT / "evidence/deltahls_residual_p4_k1_v1/summary.json",
    "direct_k4": ROOT
    / "evidence/deltahls_residual_p4_direct_k4_v1/summary.json",
    "shared_k4": ROOT
    / "evidence/deltahls_residual_p4_shared_k4_v1/summary.json",
}


def _only_row(payload: Mapping[str, Any], label: str) -> dict[str, Any]:
    rows = payload.get("runs")
    if not isinstance(rows, list) or len(rows) != 1 or not isinstance(rows[0], dict):
        raise ValueError(f"{label} must contain exactly one run row")
    if payload.get("all_correct") is not True:
        raise ValueError(f"{label} failed correctness admission")
    return rows[0]


def analyze_payloads(payloads: Mapping[str, Mapping[str, Any]]) -> dict[str, Any]:
    expected = {"spine", "k1", "direct_k4", "shared_k4"}
    if set(payloads) != expected:
        raise ValueError("scalability analysis requires four frozen variants")
    rows = {label: _only_row(payloads[label], label) for label in expected}
    spine = rows["spine"]
    k1 = rows["k1"]
    direct = rows["direct_k4"]
    shared = rows["shared_k4"]
    common_fields = (
        "run_id",
        "epsilon",
        "damping",
        "vertices",
        "initial_edges",
        "user_mutations",
        "physical_records",
        "iterations",
        "active_edges",
    )
    common_match = all(
        len({rows[label][field] for label in expected}) == 1
        for field in common_fields
    )
    residual_match = max(
        float(rows[label]["residual_linf"]) for label in expected
    ) - min(float(rows[label]["residual_linf"]) for label in expected) <= 1.0e-12
    grasu_ledger_match = len(
        {
            (rows[label]["backend_requests"], rows[label]["backend_bytes"])
            for label in ("k1", "direct_k4", "shared_k4")
        }
    ) == 1
    topology_match = (
        k1["compute_pipelines"] == 1
        and k1["downstream_sharing"] == "direct"
        and k1["max_parallel_partitions"] == 1
        and k1["max_parallel_downstream_partitions"] == 1
        and direct["compute_pipelines"] == 4
        and direct["downstream_sharing"] == "direct"
        and direct["max_parallel_partitions"] == 4
        and direct["max_parallel_downstream_partitions"] == 4
        and shared["compute_pipelines"] == 4
        and shared["downstream_sharing"] == "shared"
        and shared["max_parallel_partitions"] == 4
        and shared["max_parallel_downstream_partitions"] == 1
    )
    provenance_match = (
        len({payloads[label]["input_manifest_sha256"] for label in expected}) == 1
        and len({payloads[label]["sst_plugin_sha256"] for label in expected}) == 1
        and payloads["direct_k4"]["grasu_profile_sha256"]
        == payloads["shared_k4"]["grasu_profile_sha256"]
    )
    checks = {
        "common_work_and_state": common_match and residual_match,
        "grasu_request_and_byte_conservation": grasu_ledger_match,
        "parallel_topology": topology_match,
        "provenance": provenance_match,
        "positive_cycles": all(int(row["cycles"]) > 0 for row in rows.values()),
    }
    failed = [name for name, passed in checks.items() if not passed]
    if failed:
        raise ValueError(f"residual scalability evidence failed: {failed}")
    metrics = {
        "k1_to_direct_k4_speedup": k1["time_us"] / direct["time_us"],
        "k1_to_shared_k4_speedup": k1["time_us"] / shared["time_us"],
        "shared_k4_penalty_over_direct": shared["time_us"] / direct["time_us"],
        "spine_speedup_over_k1": k1["time_us"] / spine["time_us"],
        "spine_speedup_over_direct_k4": direct["time_us"] / spine["time_us"],
        "spine_speedup_over_shared_k4": shared["time_us"] / spine["time_us"],
    }
    if not all(math.isfinite(value) and value > 0.0 for value in metrics.values()):
        raise ValueError("residual scalability metrics are invalid")
    return {
        "schema_version": 1,
        "analysis_id": "deltahls_residual_p4_scalability_v1",
        "status": "PASS",
        "checks": checks,
        "metrics": metrics,
        "rows": [rows[label] for label in ("spine", "k1", "direct_k4", "shared_k4")],
        "limitations": [
            "The balanced four-partition matching graph is synthetic.",
            "Direct K4 models four downstreams; shared K4 schedules one partition-granular downstream.",
            "Shared K4 resource feasibility still requires HLS synthesis evidence.",
        ],
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--spine", type=Path, default=DEFAULT_INPUTS["spine"])
    parser.add_argument("--k1", type=Path, default=DEFAULT_INPUTS["k1"])
    parser.add_argument(
        "--direct-k4", type=Path, default=DEFAULT_INPUTS["direct_k4"]
    )
    parser.add_argument(
        "--shared-k4", type=Path, default=DEFAULT_INPUTS["shared_k4"]
    )
    parser.add_argument("--out-dir", type=Path, required=True)
    args = parser.parse_args()
    paths = {
        "spine": args.spine,
        "k1": args.k1,
        "direct_k4": args.direct_k4,
        "shared_k4": args.shared_k4,
    }
    payloads = {
        label: json.loads(path.read_text(encoding="utf-8"))
        for label, path in paths.items()
    }
    analysis = analyze_payloads(payloads)
    args.out_dir.mkdir(parents=True, exist_ok=True)
    (args.out_dir / "summary.json").write_text(
        json.dumps(analysis, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    rows = analysis["rows"]
    compact_rows = [
        {
            key: row[key]
            for key in (
                "architecture",
                "compute_pipelines",
                "downstream_sharing",
                "max_parallel_partitions",
                "max_parallel_downstream_partitions",
                "cycles",
                "time_us",
                "backend_requests",
                "backend_bytes",
                "iterations",
                "active_edges",
                "correctness_mismatches",
            )
        }
        for row in rows
    ]
    with (args.out_dir / "rows.csv").open(
        "w", encoding="ascii", newline=""
    ) as stream:
        writer = csv.DictWriter(stream, fieldnames=list(compact_rows[0]))
        writer.writeheader()
        writer.writerows(compact_rows)
    print(
        "PASS Delta.hls residual scalability: "
        f"direct={analysis['metrics']['k1_to_direct_k4_speedup']:.3f}x "
        f"shared={analysis['metrics']['k1_to_shared_k4_speedup']:.3f}x"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
