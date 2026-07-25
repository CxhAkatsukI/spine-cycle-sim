#!/usr/bin/env python3
"""Analyze matched Full and residual PageRank partial energy evidence."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from spine_cycle_sim.evidence.matched_energy import (  # noqa: E402
    analyze_matched_pagerank_energy,
    flatten_component_rows,
    flatten_system_rows,
    write_csv,
)


DEFAULT_ROOT = ROOT / "docs" / "evidence" / "matched_partial_energy_20260726"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--full-dir", type=Path, default=DEFAULT_ROOT / "raw" / "full_pagerank"
    )
    parser.add_argument(
        "--residual-dir",
        type=Path,
        default=DEFAULT_ROOT / "raw" / "residual_pagerank",
    )
    parser.add_argument(
        "--cacti-manifest",
        type=Path,
        default=DEFAULT_ROOT / "raw" / "cacti" / "cacti_manifest.json",
    )
    parser.add_argument("--out-dir", type=Path, default=DEFAULT_ROOT)
    args = parser.parse_args()
    ledger = analyze_matched_pagerank_energy(
        args.full_dir, args.residual_dir, args.cacti_manifest
    )
    args.out_dir.mkdir(parents=True, exist_ok=True)
    (args.out_dir / "matched_energy.json").write_text(
        json.dumps(ledger, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    write_csv(args.out_dir / "system_energy.csv", flatten_system_rows(ledger))
    write_csv(args.out_dir / "component_energy.csv", flatten_component_rows(ledger))
    write_csv(args.out_dir / "pair_energy.csv", ledger["pairs"])
    print(
        f"PASS matched partial energy: systems={len(ledger['system_rows'])} "
        f"pairs={len(ledger['pairs'])}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
