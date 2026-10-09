#!/usr/bin/env python3
"""Check the unmodified GraSU source16 search/dispatch/cache/DDR path, not timing."""

import argparse
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from spine_cycle_sim.experiments.upstream_controls.grasu.analysis import STATUS
from spine_cycle_sim.experiments.upstream_controls.grasu.study import run


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, default=ROOT / "build/publication_sources/grasu")
    parser.add_argument("--hls-include", type=Path, required=True)
    parser.add_argument("--baseline", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    report = run(ROOT, args.source.resolve(), args.hls_include.resolve(), args.baseline.resolve(), args.out.resolve())
    print(f"{report['status']}: {args.out / 'report.json'}")
    return int(report["status"] != STATUS)


if __name__ == "__main__": raise SystemExit(main())
