#!/usr/bin/env python3
"""Run one Spine v0 simulator workload."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from spine_cycle_sim.models import SpineV0Simulator, load_config
from spine_cycle_sim.stats.io import write_json, write_summary_csv
from spine_cycle_sim.workloads import generate_workload, list_workloads


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--workload", required=True, choices=list_workloads())
    parser.add_argument("--vertices", type=int, required=True)
    parser.add_argument("--edges", type=int, default=None)
    parser.add_argument("--source", type=int, default=0)
    parser.add_argument("--seed", type=int, default=1)
    parser.add_argument("--config", default="configs/spine_current.yaml")
    parser.add_argument("--out-dir", type=Path, default=None)
    parser.add_argument("--case", default=None)
    parser.add_argument("--dump-trace", action="store_true")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    config = load_config(args.config)
    workload = generate_workload(
        args.workload,
        vertices=args.vertices,
        edges=args.edges,
        source=args.source,
        num_partitions=config.num_partitions,
        seed=args.seed,
    )
    if args.case:
        workload.metadata["case"] = args.case
    sim = SpineV0Simulator(workload, config)
    result = sim.run(include_trace=args.dump_trace)

    if args.out_dir is not None:
        args.out_dir.mkdir(parents=True, exist_ok=True)
        case = str(result["case"])
        write_json(args.out_dir / f"{case}.json", result)
        write_summary_csv(args.out_dir / f"{case}.csv", [result])
        write_summary_csv(args.out_dir / "summary.csv", [result])

    print(json.dumps(result, indent=2, sort_keys=True))
    return 1 if result.get("capacity_status") == "FAIL" else 0


if __name__ == "__main__":
    raise SystemExit(main())
