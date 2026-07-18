#!/usr/bin/env python3
"""Analyze Phase 2B HW maintenance calibration logs."""

from __future__ import annotations

import argparse
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from spine_cycle_sim.calibration import (  # noqa: E402
    aggregate_rows,
    analyze_summary,
    merge_simulator_counters,
    read_rows_csv,
    write_json,
    write_rows_csv,
)
from spine_cycle_sim.calibration.maintenance import (  # noqa: E402
    DEFAULT_FREQ_MHZ,
    SUMMARY_FIELD_ORDER,
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input-dir", type=Path, required=True)
    parser.add_argument("--out-dir", type=Path)
    parser.add_argument("--freq-mhz", type=float, default=DEFAULT_FREQ_MHZ)
    parser.add_argument("--skip-simulator", action="store_true")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    input_dir = args.input_dir
    out_dir = args.out_dir or input_dir / "analysis"
    runs_csv = input_dir / "runs.csv"
    if not runs_csv.exists():
        raise SystemExit(f"missing runs.csv: {runs_csv}")
    out_dir.mkdir(parents=True, exist_ok=True)

    rows = read_rows_csv(runs_csv)
    summary = aggregate_rows(rows, freq_mhz=args.freq_mhz)
    if not args.skip_simulator:
        summary = merge_simulator_counters(summary)
    analysis = analyze_summary(summary)

    write_rows_csv(out_dir / "summary.csv", summary, SUMMARY_FIELD_ORDER)
    write_json(out_dir / "summary.json", summary)
    write_json(out_dir / "fit.json", analysis)

    print(f"wrote summary: {out_dir / 'summary.csv'}")
    print(f"wrote fit: {out_dir / 'fit.json'}")
    ridge = analysis.get("ridge", {})
    carry = analysis.get("ridge_carry", {})
    print(
        "overall ridge: "
        f"samples={ridge.get('samples')} r2={ridge.get('r2')} "
        f"median_abs_pct_error={ridge.get('median_abs_pct_error')}"
    )
    print(
        "carry ridge: "
        f"samples={carry.get('samples')} r2={carry.get('r2')} "
        f"median_abs_pct_error={carry.get('median_abs_pct_error')}"
    )
    top = analysis.get("univariate", [])[:5]
    if top:
        print("top univariate features:")
        for item in top:
            print(
                f"  {item['feature']}: r2={item['r2']:.4f} "
                f"range_cycles={item['dynamic_range_cycles']:.1f}"
            )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
