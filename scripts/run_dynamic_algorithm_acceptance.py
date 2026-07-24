#!/usr/bin/env python3
"""Run reproducible dynamic-update correctness cases for all algorithm policies."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from spine_cycle_sim.algorithms import (
    AlgorithmConfig,
    DynamicGraph,
    EdgeUpdate,
    FullPageRankPolicy,
    ResidualPageRankPolicy,
    UpdateOperation,
    WeightedSsspPolicy,
    run_dynamic_dual_oracle,
)
from spine_cycle_sim.workloads import Edge


def summarize(name: str, result: Any) -> dict[str, Any]:
    batches: list[dict[str, Any]] = []
    for mathematical, architecture, numeric in zip(
        result.mathematical.batches,
        result.architecture.batches,
        result.batches,
        strict=True,
    ):
        batches.append(
            {
                "batch": mathematical.batch_index,
                "mode": mathematical.execution_mode.value,
                "changes": [
                    {
                        "src": change.src,
                        "dst": change.dst,
                        "old_weight": change.old_weight,
                        "new_weight": change.new_weight,
                    }
                    for change in mathematical.effect.changes
                ],
                "mathematical_oracle_match": mathematical.oracle_match,
                "architecture_oracle_match": architecture.oracle_match,
                "mathematical_iterations": mathematical.result.stats.iterations,
                "architecture_iterations": architecture.result.stats.iterations,
                "mathematical_mapped_edges": mathematical.result.stats.mapped_edges,
                "architecture_mapped_edges": architecture.result.stats.mapped_edges,
                "numeric_exact_match": numeric.exact_match,
                "numeric_l1_difference": numeric.l1_difference,
                "numeric_max_abs_difference": numeric.max_abs_difference,
            }
        )
    return {"algorithm": name, "batches": batches}


def build_results() -> list[dict[str, Any]]:
    sssp_graph = DynamicGraph.from_edges(
        4,
        [
            Edge(0, 1, 5),
            Edge(1, 2, 5),
            Edge(0, 2, 20),
            Edge(2, 3, 1),
        ],
    )
    sssp = run_dynamic_dual_oracle(
        sssp_graph,
        [
            [EdgeUpdate(0, 2, 2)],
            [EdgeUpdate(0, 2, 2, UpdateOperation.DELETE)],
            [EdgeUpdate(1, 2, 50)],
        ],
        WeightedSsspPolicy(),
        AlgorithmConfig(source=0),
    )

    full_graph = DynamicGraph.from_edges(
        4, [Edge(0, 1), Edge(1, 2), Edge(2, 3), Edge(3, 0)]
    )
    full = run_dynamic_dual_oracle(
        full_graph,
        [
            [EdgeUpdate(0, 2)],
            [EdgeUpdate(2, 3, operation=UpdateOperation.DELETE)],
        ],
        FullPageRankPolicy(),
        AlgorithmConfig(epsilon=1e-6, max_iterations=300),
    )

    residual_graph = DynamicGraph.from_edges(
        4,
        [Edge(0, 1), Edge(1, 0), Edge(1, 2), Edge(2, 3), Edge(3, 1)],
    )
    residual = run_dynamic_dual_oracle(
        residual_graph,
        [
            [EdgeUpdate(0, 2)],
            [EdgeUpdate(1, 2, operation=UpdateOperation.DELETE)],
        ],
        ResidualPageRankPolicy(),
        AlgorithmConfig(epsilon=1e-7, max_iterations=500),
    )
    return [
        summarize("weighted_sssp", sssp),
        summarize("full_pagerank", full),
        summarize("thresholded_residual_pagerank", residual),
    ]


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()

    algorithms = build_results()
    all_batches = [batch for algorithm in algorithms for batch in algorithm["batches"]]
    passed = all(
        batch["mathematical_oracle_match"]
        and batch["architecture_oracle_match"]
        for batch in all_batches
    )
    payload = {
        "status": "PASS" if passed else "FAIL",
        "claim_tier": "functional_oracle_not_cycle_timed",
        "algorithms": algorithms,
    }
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    print(
        f"{payload['status']} dynamic algorithms: "
        f"algorithms={len(algorithms)} batches={len(all_batches)} -> {args.out}"
    )
    return 0 if passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
