#!/usr/bin/env python3
"""Validate exact-idle results against an always-clocked HBM sweep."""

from __future__ import annotations

import argparse
import csv
import json
from pathlib import Path
import sys


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from spine_cycle_sim.evidence.exact_idle import (  # noqa: E402
    analyze_exact_idle_sensitivity_equivalence,
)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--baseline-dir", type=Path, required=True)
    parser.add_argument("--candidate-dir", type=Path, required=True)
    parser.add_argument("--out-dir", type=Path, required=True)
    args = parser.parse_args()
    result = analyze_exact_idle_sensitivity_equivalence(
        args.baseline_dir, args.candidate_dir
    )
    args.out_dir.mkdir(parents=True, exist_ok=True)
    rows = result.pop("rows")
    (args.out_dir / "equivalence_manifest.json").write_text(
        json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    with (args.out_dir / "equivalence_rows.csv").open(
        "w", encoding="utf-8", newline=""
    ) as stream:
        writer = csv.DictWriter(stream, fieldnames=list(rows[0]), lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)
    print(
        "PASS exact-idle HBM sensitivity equivalence: "
        f"profiles={len(result['profiles'])} "
        f"results={result['system_results']} "
        f"dram_json={result['dram_json_files_compared']} "
        f"host_geomean={result['host_speedup_geomean']:.3f}x"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
