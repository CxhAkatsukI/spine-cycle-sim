#!/usr/bin/env python3
"""Index all upstream HLS attempts and their structured scheduling evidence."""

from __future__ import annotations

import argparse
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from spine_cycle_sim.experiments.upstream_controls.hls_analysis import analyze_study  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--runs", type=Path, nargs="+", required=True)
    parser.add_argument("--source-contracts", type=Path, nargs="+", required=True)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    report = analyze_study([path.resolve() for path in args.runs],
                           [path.resolve() for path in args.source_contracts], args.out.resolve())
    print(f"Indexed {report['attempts']} attempts: {args.out.resolve()}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
