#!/usr/bin/env python3
"""Audit and summarize the frozen connected-components publication evidence."""

from __future__ import annotations

import argparse
import csv
import json
import math
from pathlib import Path
from typing import Any, Mapping


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_INPUTS = {
    "k1": ROOT / "evidence/cc_k1_publication_v1/summary.json",
    "p4_k1": ROOT / "evidence/cc_scalability_p4_k1_v3/summary.json",
    "p4_direct_k4": ROOT
    / "evidence/cc_scalability_p4_direct_k4_v2/summary.json",
    "p4_shared_k4": ROOT
    / "evidence/cc_scalability_p4_shared_k4_v1/summary.json",
}
SCREENING_IDS = (
    "cc_real_soc_flickr_insert_u1",
    "cc_real_soc_flickr_insert_u8",
    "cc_real_soc_flickr_insert_u64",
    "cc_real_soc_flickr_insert_u4096",
)
SCALABILITY_ID = "cc_real_soc_flickr_replicated_p4_insert_u4"


def _rows_by_architecture(
    payload: Mapping[str, Any], run_id: str
) -> dict[str, Mapping[str, Any]]:
    rows = [row for row in payload.get("rows", []) if row.get("run_id") == run_id]
    return {str(row["architecture"]): row for row in rows}


def _summary_passes(payload: Mapping[str, Any]) -> bool:
    return (
        payload.get("all_correct") is True
        and payload.get("all_admission_checks_passed") is True
    )


def _provenance(row: Mapping[str, Any]) -> tuple[str, str, str, str]:
    return tuple(
        str(row[key])
        for key in (
            "source_revision",
            "workload_sha256",
            "update_sha256",
            "sst_plugin_sha256",
        )
    )  # type: ignore[return-value]


def _compact(row: Mapping[str, Any], variant: str) -> dict[str, Any]:
    return {
        "variant": variant,
        "run_id": row["run_id"],
        "architecture": row["architecture"],
        "logical_user_mutations": row["logical_user_mutations"],
        "vertices": row["vertices"],
        "initial_edges": row["initial_edges"],
        "iterations": row["iterations"],
        "active_edges": row["active_edges"],
        "compute_pipelines": row["compute_pipelines"],
        "downstream_sharing": row["downstream_sharing"],
        "max_parallel_partitions": row["max_parallel_partitions"],
        "max_parallel_downstream_partitions": row[
            "max_parallel_downstream_partitions"
        ],
        "cycles": row["cycles"],
        "backend_requests": row["backend_requests"],
        "read_bytes": row["read_bytes"],
        "write_bytes": row["write_bytes"],
        "correctness_mismatches": row["correctness_mismatches"],
        "performance_admitted": row["performance_admitted"],
        "source_revision": row["source_revision"],
        "workload_sha256": row["workload_sha256"],
        "update_sha256": row["update_sha256"],
        "sst_plugin_sha256": row["sst_plugin_sha256"],
    }


def analyze_payloads(payloads: Mapping[str, Mapping[str, Any]]) -> dict[str, Any]:
    if set(payloads) != set(DEFAULT_INPUTS):
        raise ValueError("CC publication analysis requires four frozen inputs")
    summary_admission = all(_summary_passes(payload) for payload in payloads.values())

    screening_pairs: list[dict[str, Any]] = []
    screening_rows: list[dict[str, Any]] = []
    screening_match = True
    screening_provenance = True
    for run_id in SCREENING_IDS:
        rows = _rows_by_architecture(payloads["k1"], run_id)
        if set(rows) != {"spine", "grasu"}:
            raise ValueError(f"missing K1 architecture pair for {run_id}")
        spine, grasu = rows["spine"], rows["grasu"]
        screening_match &= all(
            spine[key] == grasu[key]
            for key in (
                "vertices",
                "initial_edges",
                "logical_user_mutations",
                "effective_mutations",
                "physical_records",
                "initial_components",
                "final_components",
                "iterations",
                "active_edges",
            )
        )
        screening_match &= all(
            row["correctness_mismatches"] == 0 and row["performance_admitted"]
            for row in rows.values()
        )
        screening_provenance &= _provenance(spine) == _provenance(grasu)
        speedup = float(grasu["cycles"]) / float(spine["cycles"])
        screening_pairs.append(
            {
                "run_id": run_id,
                "user_mutations": spine["logical_user_mutations"],
                "spine_cycles": spine["cycles"],
                "grasu_cycles": grasu["cycles"],
                "spine_speedup_over_grasu": speedup,
            }
        )
        screening_rows.extend((_compact(spine, "spine_k1"), _compact(grasu, "grasu_k1")))

    p4_k1 = _rows_by_architecture(payloads["p4_k1"], SCALABILITY_ID)
    p4_direct = _rows_by_architecture(payloads["p4_direct_k4"], SCALABILITY_ID)
    p4_shared = _rows_by_architecture(payloads["p4_shared_k4"], SCALABILITY_ID)
    if set(p4_k1) != {"spine", "grasu"} or set(p4_direct) != {"grasu"} or set(
        p4_shared
    ) != {"grasu"}:
        raise ValueError("missing CC four-partition variants")
    scalability = {
        "spine": p4_k1["spine"],
        "k1": p4_k1["grasu"],
        "direct_k4": p4_direct["grasu"],
        "shared_k4": p4_shared["grasu"],
    }
    work_fields = (
        "run_id",
        "vertices",
        "initial_edges",
        "logical_user_mutations",
        "effective_mutations",
        "physical_records",
        "initial_components",
        "final_components",
        "iterations",
        "active_edges",
    )
    scalability_work = all(
        len({row[field] for row in scalability.values()}) == 1
        for field in work_fields
    )
    grasu_traffic = len(
        {
            (
                scalability[label]["backend_requests"],
                scalability[label]["read_bytes"],
                scalability[label]["write_bytes"],
            )
            for label in ("k1", "direct_k4", "shared_k4")
        }
    ) == 1
    topology = (
        scalability["k1"]["compute_pipelines"] == 1
        and scalability["k1"]["max_parallel_partitions"] == 1
        and scalability["k1"]["max_parallel_downstream_partitions"] == 1
        and scalability["direct_k4"]["compute_pipelines"] == 4
        and scalability["direct_k4"]["downstream_sharing"] == "direct"
        and scalability["direct_k4"]["max_parallel_partitions"] == 4
        and scalability["direct_k4"]["max_parallel_downstream_partitions"] == 4
        and scalability["shared_k4"]["compute_pipelines"] == 4
        and scalability["shared_k4"]["downstream_sharing"] == "shared"
        and scalability["shared_k4"]["max_parallel_partitions"] == 4
        and scalability["shared_k4"]["max_parallel_downstream_partitions"] == 1
    )
    scalability_correct = all(
        row["correctness_mismatches"] == 0 and row["performance_admitted"]
        for row in scalability.values()
    )
    scalability_provenance = len({_provenance(row) for row in scalability.values()}) == 1
    checks = {
        "summary_admission": summary_admission,
        "screening_work_and_correctness": screening_match,
        "screening_provenance": screening_provenance,
        "scalability_work_and_correctness": scalability_work and scalability_correct,
        "scalability_grasu_traffic_conservation": grasu_traffic,
        "scalability_parallel_topology": topology,
        "scalability_provenance": scalability_provenance,
        "positive_cycles": all(
            int(row["cycles"]) > 0
            for row in screening_rows + list(scalability.values())
        ),
    }
    failed = [name for name, passed in checks.items() if not passed]
    if failed:
        raise ValueError(f"CC publication evidence failed: {failed}")
    k1 = scalability["k1"]
    direct = scalability["direct_k4"]
    shared = scalability["shared_k4"]
    spine = scalability["spine"]
    metrics = {
        "k1_to_direct_k4_speedup": k1["cycles"] / direct["cycles"],
        "k1_to_shared_k4_speedup": k1["cycles"] / shared["cycles"],
        "shared_k4_penalty_over_direct": shared["cycles"] / direct["cycles"],
        "spine_speedup_over_k1": k1["cycles"] / spine["cycles"],
        "spine_speedup_over_direct_k4": direct["cycles"] / spine["cycles"],
        "spine_speedup_over_shared_k4": shared["cycles"] / spine["cycles"],
    }
    if not all(math.isfinite(value) and value > 0 for value in metrics.values()):
        raise ValueError("CC publication metrics are invalid")
    return {
        "schema_version": 1,
        "analysis_id": "connected_components_publication_v1",
        "status": "PASS",
        "checks": checks,
        "screening_pairs": screening_pairs,
        "scalability_metrics": metrics,
        "scalability_rows": [
            _compact(scalability[label], label)
            for label in ("spine", "k1", "direct_k4", "shared_k4")
        ],
        "limitations": [
            "K1 screening uses a compact 2,552-vertex real Flickr topology slice.",
            "K4 scalability uses a synthetic four-way replication of that slice.",
            "The CC contract supports insertion-only incremental repair; deletion repair is out of scope.",
        ],
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    for label, path in DEFAULT_INPUTS.items():
        parser.add_argument(f"--{label.replace('_', '-')}", type=Path, default=path)
    parser.add_argument("--out-dir", type=Path, required=True)
    args = parser.parse_args()
    paths = {label: getattr(args, label) for label in DEFAULT_INPUTS}
    payloads = {
        label: json.loads(path.read_text(encoding="utf-8"))
        for label, path in paths.items()
    }
    analysis = analyze_payloads(payloads)
    args.out_dir.mkdir(parents=True, exist_ok=True)
    (args.out_dir / "summary.json").write_text(
        json.dumps(analysis, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    rows = analysis["scalability_rows"]
    with (args.out_dir / "scalability_rows.csv").open(
        "w", encoding="ascii", newline=""
    ) as stream:
        writer = csv.DictWriter(stream, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)
    pairs = analysis["screening_pairs"]
    with (args.out_dir / "screening_pairs.csv").open(
        "w", encoding="ascii", newline=""
    ) as stream:
        writer = csv.DictWriter(stream, fieldnames=list(pairs[0]))
        writer.writeheader()
        writer.writerows(pairs)
    print(
        "PASS CC publication evidence: "
        f"direct={analysis['scalability_metrics']['k1_to_direct_k4_speedup']:.3f}x "
        f"shared={analysis['scalability_metrics']['k1_to_shared_k4_speedup']:.3f}x"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
