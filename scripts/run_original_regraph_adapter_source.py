#!/usr/bin/env python3
"""Validate existing sharded PMA adapter source and exact shared-A4 wiring regression."""

import argparse
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from spine_cycle_sim.experiments.original_regraph_execution.adapter.analysis import STATUS
from spine_cycle_sim.experiments.original_regraph_execution.adapter.study import run


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--adapter-source", type=Path, required=True)
    parser.add_argument("--hls-include", type=Path, required=True)
    parser.add_argument("--input-run", type=Path, required=True)
    parser.add_argument("--baseline", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    report = run(ROOT, args.adapter_source.resolve(), args.hls_include.resolve(), args.input_run.resolve(), args.baseline.resolve(), args.out.resolve())
    print(f"{report['status']}: {args.out / 'report.json'}")
    return int(report["status"] != STATUS)


if __name__ == "__main__": raise SystemExit(main())
