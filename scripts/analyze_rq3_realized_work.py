#!/usr/bin/env python3
"""Analyze Spine realized work against overlap-aware execution time."""

from __future__ import annotations

import argparse
from pathlib import Path
import sys


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from spine_cycle_sim.experiments.publication_analysis import load_case_results  # noqa: E402
from spine_cycle_sim.experiments.rq3 import (  # noqa: E402
    analyze_rq3_results,
    write_rq3_analysis,
)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--result-root", type=Path, action="append", required=True)
    parser.add_argument("--out-dir", type=Path, required=True)
    parser.add_argument(
        "--preferred-plugin-sha256",
        action="append",
        default=[],
        help="repeat in newest-to-oldest admission order",
    )
    args = parser.parse_args()
    analysis = analyze_rq3_results(
        load_case_results(args.result_root),
        preferred_plugin_sha256=args.preferred_plugin_sha256,
    )
    write_rq3_analysis(args.out_dir, analysis)
    print(
        f"RQ3 rows={len(analysis['work_rows'])} "
        f"regressions={len(analysis['regression_rows'])}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
