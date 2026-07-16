#!/usr/bin/env python3
"""Run the validation-oriented Spine v0 workload suite."""

from __future__ import annotations

import argparse
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from spine_cycle_sim.models import SpineV0Simulator, load_config
from spine_cycle_sim.stats.io import write_json, write_summary_csv
from spine_cycle_sim.workloads import generate_workload


PROD_VERTICES = 16_777_216

SUITE = [
    {"case": "small_chain_v64", "workload": "chain", "vertices": 64, "edges": 63, "source": 0},
    {"case": "small_star_v4096_u1024", "workload": "star", "vertices": PROD_VERTICES, "edges": 1024, "source": 0},
    {"case": "small_spread_v4096_u1024", "workload": "spread", "vertices": PROD_VERTICES, "edges": 1024, "source": 0},
    {"case": "small_hotdst_v4096_u1024", "workload": "hotdst", "vertices": PROD_VERTICES, "edges": 1024, "source": 0},
    {
        "case": "balanced_full_plus_one",
        "workload": "balanced_partition",
        "vertices": PROD_VERTICES,
        "edges": 131073,
        "source": 0,
    },
    {
        "case": "one_partition_full_plus_one",
        "workload": "hotdst",
        "vertices": PROD_VERTICES,
        "edges": 131073,
        "source": 0,
    },
    {
        "case": "large_chain_v4096",
        "workload": "chain",
        "vertices": 4096,
        "edges": 4095,
        "source": 0,
    },
    {
        "case": "large_star_v1048576_u65536",
        "workload": "star",
        "vertices": PROD_VERTICES,
        "edges": 262144,
        "source": 0,
    },
    {
        "case": "large_spread_v262144_u65536",
        "workload": "spread",
        "vertices": PROD_VERTICES,
        "edges": 262144,
        "source": 0,
    },
    {
        "case": "large_hotdst_v262144_u65536",
        "workload": "hotdst",
        "vertices": PROD_VERTICES,
        "edges": 262144,
        "source": 0,
    },
    {"case": "random_rmat_small", "workload": "random_rmat", "vertices": PROD_VERTICES, "edges": 4096, "source": 0},
]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", default="configs/spine_current.yaml")
    parser.add_argument("--out-dir", type=Path, required=True)
    parser.add_argument("--dump-trace", action="store_true")
    parser.add_argument("--keep-going", action="store_true", default=True)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    config = load_config(args.config)
    args.out_dir.mkdir(parents=True, exist_ok=True)
    rows = []
    for spec in SUITE:
        workload = generate_workload(
            spec["workload"],
            vertices=spec["vertices"],
            edges=spec["edges"],
            source=spec["source"],
            num_partitions=config.num_partitions,
            vs_partition_size=config.vs_partition_size,
        )
        workload.metadata["case"] = spec["case"]
        result = SpineV0Simulator(workload, config).run(include_trace=args.dump_trace)
        rows.append(result)
        write_json(args.out_dir / f"{spec['case']}.json", result)
        write_summary_csv(args.out_dir / f"{spec['case']}.csv", [result])
        print(
            f"{spec['case']}: {result['capacity_status']} "
            f"cycles={result['cycles']} carry={result['carry_count']} "
            f"hbm_req={result['hbm_request_count']}"
        )
    write_summary_csv(args.out_dir / "summary.csv", rows)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
