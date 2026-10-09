#!/usr/bin/env python3
"""Validate bounded original GraSU host repair and full source16 functional composition."""

import argparse
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from spine_cycle_sim.experiments.upstream_controls.grasu.host.analysis import STATUS
from spine_cycle_sim.experiments.upstream_controls.grasu.host.study import run


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, default=ROOT / "build/publication_sources/grasu")
    parser.add_argument("--hls-include", type=Path, required=True)
    parser.add_argument("--xrt-include", type=Path, default=Path("/opt/xilinx/xrt/include"))
    parser.add_argument("--baseline", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    result = run(ROOT, args.source.resolve(), args.hls_include.resolve(), args.xrt_include.resolve(), args.baseline.resolve(), args.out.resolve())
    print(f"{result['status']}: {args.out / 'report.json'}")
    return int(result["status"] != STATUS)


if __name__ == "__main__": raise SystemExit(main())
