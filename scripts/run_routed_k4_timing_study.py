#!/usr/bin/env python3
"""Run one bounded actual-HLS-input routed SSSP timing diagnostic."""

import argparse
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from spine_cycle_sim.experiments.sharded_k4_stages.sst_timing import run_sst_case


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("integration", "plugin-dir", "exporter", "graph", "board-run", "output"):
        parser.add_argument(f"--{name}", required=True, type=Path)
    parser.add_argument("--profile", type=Path,
                        default=ROOT / "configs/architectures/grasu_regraph_routed_sssp_compute_v1.json")
    parser.add_argument("--source", type=int, required=True)
    parser.add_argument("--arm", choices=("original", "candidate"), default="candidate")
    parser.add_argument("--timeout", type=int, default=600)
    parser.add_argument("--max-cycles", type=int, default=300000000)
    args = parser.parse_args()
    result = run_sst_case(root=ROOT, integration=args.integration.resolve(), plugin_dir=args.plugin_dir.resolve(),
                          exporter=args.exporter.resolve(), profile_path=args.profile.resolve(),
                          graph=args.graph.resolve(), source=args.source, board_run=args.board_run.resolve(),
                          output=args.output.resolve(), arm=args.arm, timeout=args.timeout, max_cycles=args.max_cycles)
    print(result["status"], result["timing"], flush=True)


if __name__ == "__main__":
    main()
