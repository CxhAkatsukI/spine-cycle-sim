#!/usr/bin/env python3
"""Audit the >=540k-edge weighted SSSP, CC, and residual PageRank results."""

from __future__ import annotations

import argparse
import csv
import json
import math
from pathlib import Path
from typing import Any, Mapping, Sequence


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_WEIGHTED = Path(
    "/data/tmp/chuxiao/opt_v2_k1_askubuntu540k_weighted_formal_v2_20260728"
)
DEFAULT_CC_GATE = ROOT / "evidence/askubuntu_reciprocal_large_cc_k1_matrix_v1"
DEFAULT_RESIDUAL_GATE = (
    ROOT / "evidence/askubuntu_reciprocal_large_residual_k1_matrix_v1"
)
DEFAULT_CC_FULL = ROOT / "evidence/askubuntu_reciprocal_full_cc_k1_matrix_v1"
DEFAULT_RESIDUAL_FULL = (
    ROOT / "evidence/askubuntu_reciprocal_full_residual_k1_matrix_v1"
)
DEFAULT_GATE_MANIFEST = (
    ROOT / "configs/experiments/askubuntu_reciprocal_large_v1.json"
)
DEFAULT_FULL_MANIFEST = (
    ROOT / "configs/experiments/askubuntu_reciprocal_full_v1.json"
)
DEFAULT_WEIGHTED_INPUT = (
    ROOT
    / "configs/experiments/candidate10_grasu_askubuntu_paper_scale_v1_20260728.json"
)


def _float(row: Mapping[str, Any], key: str) -> float:
    return float(row[key])


def _int(row: Mapping[str, Any], key: str) -> int:
    return int(row[key])


def _speedup(value: float) -> float:
    if not math.isfinite(value) or value <= 0:
        raise ValueError("large-real speedup must be finite and positive")
    return value


def _cc_pairs(summary: Mapping[str, Any]) -> list[dict[str, Any]]:
    if not summary.get("all_correct") or not summary.get(
        "all_admission_checks_passed"
    ):
        raise ValueError("CC large-real summary failed admission")
    rows_by_run: dict[str, dict[str, Mapping[str, Any]]] = {}
    for row in summary["rows"]:
        rows_by_run.setdefault(str(row["run_id"]), {})[
            str(row["architecture"])
        ] = row
    output = []
    for pair in summary["pairs"]:
        rows = rows_by_run[str(pair["run_id"])]
        if set(rows) != {"spine", "grasu"}:
            raise ValueError("CC large-real pair is incomplete")
        spine, grasu = rows["spine"], rows["grasu"]
        if not pair["performance_admitted"] or any(
            row["correctness_mismatches"] != 0 for row in rows.values()
        ):
            raise ValueError("CC large-real pair failed correctness")
        for key in (
            "vertices",
            "initial_edges",
            "logical_user_mutations",
            "initial_components",
            "final_components",
            "iterations",
            "active_edges",
        ):
            if spine[key] != grasu[key]:
                raise ValueError(f"CC cross-system work mismatch: {key}")
        output.append(
            {
                "run_id": pair["run_id"],
                "user_mutations": spine["logical_user_mutations"],
                "vertices": spine["vertices"],
                "initial_edges": spine["initial_edges"],
                "iterations": spine["iterations"],
                "active_edges": spine["active_edges"],
                "spine_cycles": spine["cycles"],
                "grasu_cycles": grasu["cycles"],
                "spine_speedup_over_grasu": _speedup(
                    float(pair["spine_speedup_over_grasu"])
                ),
                "spine_backend_bytes": spine["read_bytes"] + spine["write_bytes"],
                "grasu_backend_bytes": grasu["read_bytes"] + grasu["write_bytes"],
            }
        )
    return sorted(output, key=lambda row: row["user_mutations"])


def _residual_pairs(summary: Mapping[str, Any]) -> list[dict[str, Any]]:
    if not summary.get("all_correct"):
        raise ValueError("residual large-real summary failed correctness")
    rows_by_run: dict[str, dict[str, Mapping[str, Any]]] = {}
    for row in summary["runs"]:
        rows_by_run.setdefault(str(row["run_id"]), {})[
            str(row["architecture"])
        ] = row
    output = []
    for pair in summary["pairs"]:
        rows = rows_by_run[str(pair["run_id"])]
        if set(rows) != {"spine", "grasu_regraph"}:
            raise ValueError("residual large-real pair is incomplete")
        spine, grasu = rows["spine"], rows["grasu_regraph"]
        if (
            not pair["correctness_admitted"]
            or not pair["cross_system_frontiers_match"]
            or _float(pair, "cross_system_max_abs_rank_difference") > 1.0e-8
            or _float(pair, "cross_system_max_abs_residual_difference") > 1.0e-8
        ):
            raise ValueError("residual large-real pair failed cross-system checks")
        for key in (
            "vertices",
            "initial_edges",
            "user_mutations",
            "iterations",
            "initial_active_vertices",
            "active_edges",
        ):
            if spine[key] != grasu[key]:
                raise ValueError(f"residual cross-system work mismatch: {key}")
        if max(float(spine["residual_linf"]), float(grasu["residual_linf"])) > 1.01e-6:
            raise ValueError("residual large-real pair exceeds per-vertex threshold")
        output.append(
            {
                "run_id": pair["run_id"],
                "user_mutations": pair["user_mutations"],
                "vertices": spine["vertices"],
                "initial_edges": spine["initial_edges"],
                "iterations": pair["iterations"],
                "active_edges": spine["active_edges"],
                "residual_linf": max(
                    float(spine["residual_linf"]), float(grasu["residual_linf"])
                ),
                "spine_cycles": pair["spine_cycles"],
                "grasu_cycles": pair["grasu_cycles"],
                "spine_speedup_over_grasu": _speedup(
                    float(pair["spine_speedup_over_grasu"])
                ),
                "spine_backend_bytes": pair["spine_backend_bytes"],
                "grasu_backend_bytes": pair["grasu_backend_bytes"],
            }
        )
    return sorted(output, key=lambda row: row["user_mutations"])


def _weighted_pairs(
    manifest: Mapping[str, Any], rows: Sequence[Mapping[str, Any]]
) -> list[dict[str, Any]]:
    if (
        manifest.get("status") != "PASS"
        or manifest.get("all_correct") is not True
        or manifest.get("complete_matrix") is not True
    ):
        raise ValueError("weighted large-real matrix failed admission")
    output = []
    for row in rows:
        if str(row.get("cross_system_distances_match")).lower() != "true":
            raise ValueError("weighted SSSP distances do not match")
        output.append(
            {
                "run_id": row["run_id"],
                "user_mutations": _int(row, "user_mutations"),
                "spine_time_ms": _float(row, "spine_aligned_e2e_ms"),
                "grasu_time_ms": _float(row, "grasu_aligned_e2e_ms"),
                "spine_speedup_over_grasu": _speedup(
                    _float(row, "spine_speedup_over_grasu_e2e")
                ),
            }
        )
    if sorted(row["user_mutations"] for row in output) != [8, 64, 4096]:
        raise ValueError("weighted SSSP large-real batches changed")
    return sorted(output, key=lambda row: row["user_mutations"])


def _graph_contract(manifest: Mapping[str, Any]) -> dict[str, Any]:
    graphs = {
        (
            run["graph"]["vertices"],
            run["graph"]["records"],
            run["graph"]["sha256"],
        )
        for run in manifest["runs"]
    }
    if len(graphs) != 1:
        raise ValueError("large-real manifest does not freeze one base graph")
    vertices, records, sha256 = next(iter(graphs))
    return {"vertices": vertices, "records": records, "sha256": sha256}


def analyze_payloads(
    *,
    weighted_manifest: Mapping[str, Any],
    weighted_rows: Sequence[Mapping[str, Any]],
    weighted_input: Mapping[str, Any],
    cc_gate: Mapping[str, Any],
    residual_gate: Mapping[str, Any],
    cc_full: Mapping[str, Any],
    residual_full: Mapping[str, Any],
    gate_manifest: Mapping[str, Any],
    full_manifest: Mapping[str, Any],
) -> dict[str, Any]:
    weighted = _weighted_pairs(weighted_manifest, weighted_rows)
    cc_gate_pairs = _cc_pairs(cc_gate)
    residual_gate_pairs = _residual_pairs(residual_gate)
    cc_full_pairs = _cc_pairs(cc_full)
    residual_full_pairs = _residual_pairs(residual_full)
    gate_graph = _graph_contract(gate_manifest)
    full_graph = _graph_contract(full_manifest)
    weighted_graph = _graph_contract(weighted_input)
    checks = {
        "weighted_correctness": len(weighted) == 3,
        "cc_gate_correctness": len(cc_gate_pairs) == 4,
        "residual_gate_correctness": len(residual_gate_pairs) == 4,
        "cc_full_correctness": len(cc_full_pairs) == 4,
        "residual_full_correctness": len(residual_full_pairs) == 4,
        "minimum_edge_gate": gate_graph["records"] >= 540_000,
        "full_projection_larger_than_gate": full_graph["records"] > gate_graph["records"],
        "weighted_minimum_edge_gate": weighted_graph["records"] >= 540_000,
    }
    failed = [name for name, passed in checks.items() if not passed]
    if failed:
        raise ValueError(f"large-real publication checks failed: {failed}")
    return {
        "schema_version": 1,
        "analysis_id": "large_real_three_algorithm_v1",
        "status": "PASS",
        "checks": checks,
        "weighted_sssp": {
            "input_scope": "near_full_directed_unique_real_topology",
            "graph": weighted_graph,
            "pairs": weighted,
        },
        "connected_components": {
            "input_scope": "derived_real_reciprocal_projection",
            "gate_graph": gate_graph,
            "gate_pairs": cc_gate_pairs,
            "full_graph": full_graph,
            "full_pairs": cc_full_pairs,
        },
        "residual_pagerank": {
            "contract": "per_vertex_abs_residual_gt_1e-6",
            "input_scope": "derived_real_reciprocal_sinkfree_projection",
            "gate_graph": gate_graph,
            "gate_pairs": residual_gate_pairs,
            "full_graph": full_graph,
            "full_pairs": residual_full_pairs,
        },
        "limitations": [
            "Weighted SSSP uses the directed AskUbuntu simple graph; CC and residual PageRank use declared reciprocal projections.",
            "The reciprocal updates are deterministic component bridges, not original temporal events.",
            "Results compare K1 GraSU+ReGraph against Spine; K4 large-real rows are a separate follow-up.",
        ],
    }


def _read_csv(path: Path) -> list[dict[str, str]]:
    with path.open(encoding="utf-8", newline="") as stream:
        return list(csv.DictReader(stream))


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--weighted-dir", type=Path, default=DEFAULT_WEIGHTED)
    parser.add_argument("--cc-gate-dir", type=Path, default=DEFAULT_CC_GATE)
    parser.add_argument("--residual-gate-dir", type=Path, default=DEFAULT_RESIDUAL_GATE)
    parser.add_argument("--cc-full-dir", type=Path, default=DEFAULT_CC_FULL)
    parser.add_argument("--residual-full-dir", type=Path, default=DEFAULT_RESIDUAL_FULL)
    parser.add_argument("--gate-manifest", type=Path, default=DEFAULT_GATE_MANIFEST)
    parser.add_argument("--full-manifest", type=Path, default=DEFAULT_FULL_MANIFEST)
    parser.add_argument("--weighted-input", type=Path, default=DEFAULT_WEIGHTED_INPUT)
    parser.add_argument("--out-dir", type=Path, required=True)
    args = parser.parse_args()
    load = lambda path: json.loads(path.read_text(encoding="utf-8"))
    report = analyze_payloads(
        weighted_manifest=load(args.weighted_dir / "matrix_manifest.json"),
        weighted_rows=_read_csv(args.weighted_dir / "pairs.csv"),
        weighted_input=load(args.weighted_input),
        cc_gate=load(args.cc_gate_dir / "summary.json"),
        residual_gate=load(args.residual_gate_dir / "summary.json"),
        cc_full=load(args.cc_full_dir / "summary.json"),
        residual_full=load(args.residual_full_dir / "summary.json"),
        gate_manifest=load(args.gate_manifest),
        full_manifest=load(args.full_manifest),
    )
    args.out_dir.mkdir(parents=True, exist_ok=True)
    (args.out_dir / "summary.json").write_text(
        json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    print("PASS large-real three-algorithm publication evidence")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
