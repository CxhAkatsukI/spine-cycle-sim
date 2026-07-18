#!/usr/bin/env python3
"""Run maintenance-focused microbenchmarks for the Spine simulator."""

from __future__ import annotations

import argparse
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from spine_cycle_sim.models import SpineConfig, SpineV0Simulator
from spine_cycle_sim.stats.io import write_json, write_summary_csv
from spine_cycle_sim.workloads import Edge, Workload, generate_workload


def _cold_l0_store() -> tuple[str, SpineConfig, Workload]:
    config = SpineConfig(
        max_vertices=128,
        vs_partition_size=32,
        num_partitions=4,
        hot_shards=2,
        hot_cold_enabled=False,
        batch_size_edges=64,
        num_levels=4,
        max_cycles=100_000,
    )
    workload = generate_workload(
        "hotdst",
        vertices=config.max_vertices,
        edges=8,
        source=0,
        num_partitions=config.num_partitions,
        vs_partition_size=config.vs_partition_size,
    )
    return "cold_l0_store_one_family", config, workload


def _balanced_l1_cascade() -> tuple[str, SpineConfig, Workload]:
    config = SpineConfig(
        max_vertices=128,
        vs_partition_size=32,
        num_partitions=4,
        hot_shards=2,
        hot_cold_enabled=False,
        batch_size_edges=16,
        num_levels=4,
        max_cycles=200_000,
    )
    workload = generate_workload(
        "balanced_partition",
        vertices=config.max_vertices,
        edges=20,
        source=0,
        num_partitions=config.num_partitions,
        vs_partition_size=config.vs_partition_size,
    )
    return "balanced_l1_cascade", config, workload


def _concentrated_l1_overflow() -> tuple[str, SpineConfig, Workload]:
    config = SpineConfig(
        max_vertices=128,
        vs_partition_size=32,
        num_partitions=4,
        hot_shards=2,
        hot_cold_enabled=False,
        batch_size_edges=16,
        num_levels=4,
        max_cycles=200_000,
    )
    workload = generate_workload(
        "hotdst",
        vertices=config.max_vertices,
        edges=20,
        source=0,
        num_partitions=config.num_partitions,
        vs_partition_size=config.vs_partition_size,
    )
    return "concentrated_l1_overflow", config, workload


def _duplicate_l0_coalesce() -> tuple[str, SpineConfig, Workload]:
    config = SpineConfig(
        max_vertices=16,
        vs_partition_size=16,
        num_partitions=1,
        hot_shards=1,
        hot_cold_enabled=False,
        batch_size_edges=64,
        num_levels=3,
        max_cycles=100_000,
    )
    workload = Workload(
        "duplicate_edge",
        vertices=16,
        edges=[Edge(1, 2, 1) for _ in range(20)],
        source=1,
    )
    return "duplicate_l0_coalesce", config, workload


def _hot_sparse_batches() -> tuple[str, SpineConfig, Workload]:
    config = SpineConfig(
        max_vertices=128,
        vs_partition_size=128,
        num_partitions=1,
        hot_shards=4,
        hot_cold_enabled=True,
        batch_size_edges=8,
        num_levels=3,
        max_cycles=300_000,
    )
    edges = [Edge(i, 0, 1) for i in range(8)]
    edges.extend(Edge(i % 64, (i % 56) + 1, 1) for i in range(56))
    workload = Workload("hot_sparse_batches", 128, edges, source=0)
    return "hot_zero_input_group_scans", config, workload


MICROBENCHES = [
    _cold_l0_store,
    _balanced_l1_cascade,
    _concentrated_l1_overflow,
    _duplicate_l0_coalesce,
    _hot_sparse_batches,
]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out-dir", type=Path, required=True)
    parser.add_argument("--dump-trace", action="store_true")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    args.out_dir.mkdir(parents=True, exist_ok=True)
    rows: list[dict] = []
    for build_case in MICROBENCHES:
        case, config, workload = build_case()
        workload.metadata["case"] = case
        result = SpineV0Simulator(workload, config).run(include_trace=args.dump_trace)
        rows.append(result)
        write_json(args.out_dir / f"{case}.json", result)
        write_summary_csv(args.out_dir / f"{case}.csv", [result])
        print(
            f"{case}: {result['capacity_status']} cycles={result['cycles']} "
            f"maint_cycles={result['maintenance_estimated_cycles']} "
            f"scan_passes={result['maintenance_scan_passes']} "
            f"max_target={result['maintenance_max_target_level']}"
        )
    write_summary_csv(args.out_dir / "summary.csv", rows)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
