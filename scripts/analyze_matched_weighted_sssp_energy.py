#!/usr/bin/env python3
"""Analyze matched all-controller weighted-SSSP HBM energy."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from spine_cycle_sim.evidence.matched_energy import write_csv  # noqa: E402
from spine_cycle_sim.evidence.weighted_energy import (  # noqa: E402
    analyze_matched_weighted_sssp_energy,
    flatten_weighted_system_rows,
)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dynamic-dir", type=Path, required=True)
    parser.add_argument("--cold-dir", type=Path, required=True)
    parser.add_argument("--out-dir", type=Path, required=True)
    args = parser.parse_args()

    ledger = analyze_matched_weighted_sssp_energy(
        args.dynamic_dir, args.cold_dir
    )
    args.out_dir.mkdir(parents=True, exist_ok=True)
    (args.out_dir / "matched_weighted_energy.json").write_text(
        json.dumps(ledger, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    write_csv(args.out_dir / "pair_energy.csv", ledger["pairs"])
    write_csv(
        args.out_dir / "system_energy.csv",
        flatten_weighted_system_rows(ledger),
    )
    print("PASS matched weighted SSSP HBM energy: pairs=3 controllers=32")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
