#!/usr/bin/env python3
"""Generate workload-specific component energy from frozen publication data."""

from __future__ import annotations

import argparse
import csv
import json
from pathlib import Path
import sys


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from spine_cycle_sim.evidence.workload_energy import analyze_workload_energy  # noqa: E402


def read_csv(path: Path) -> list[dict[str, str]]:
    with path.open(encoding="ascii", newline="") as stream:
        return list(csv.DictReader(stream))


def write_csv(path: Path, rows: list[dict[str, object]]) -> None:
    with path.open("w", encoding="ascii", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=list(rows[0]), lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--system-rows", type=Path, required=True)
    parser.add_argument("--activity-rows", type=Path, required=True)
    parser.add_argument("--power-rows", type=Path, required=True)
    parser.add_argument("--out-dir", type=Path, required=True)
    args = parser.parse_args()
    ledger = analyze_workload_energy(
        read_csv(args.system_rows),
        read_csv(args.activity_rows),
        read_csv(args.power_rows),
    )
    args.out_dir.mkdir(parents=True, exist_ok=True)
    (args.out_dir / "workload_energy.json").write_text(
        json.dumps(ledger, indent=2, sort_keys=True) + "\n", encoding="ascii"
    )
    for key, filename in (
        ("system_rows", "system_energy.csv"),
        ("component_rows", "component_energy.csv"),
        ("pair_rows", "pair_energy.csv"),
    ):
        write_csv(args.out_dir / filename, ledger[key])
    print(
        f"PASS workload component energy: systems={len(ledger['system_rows'])} "
        f"pairs={len(ledger['pair_rows'])}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
