#!/usr/bin/env python3
"""Export routed FPGA footprint and explicitly partial SRAM-area projection."""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
from pathlib import Path
import sys


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from spine_cycle_sim.evidence.area_projection import (  # noqa: E402
    analyze_area_projection_manifest,
)


def _write_csv(path: Path, rows: list[dict[str, object]]) -> None:
    with path.open("w", encoding="utf-8", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=list(rows[0]), lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--manifest",
        type=Path,
        default=ROOT / "configs/evidence/candidate10_area_projection_v1.json",
    )
    parser.add_argument("--out-dir", type=Path, required=True)
    parser.add_argument("--paper-data-dir", type=Path)
    args = parser.parse_args()
    ledger = analyze_area_projection_manifest(args.manifest)
    args.out_dir.mkdir(parents=True, exist_ok=True)
    (args.out_dir / "area_projection_ledger.json").write_text(
        json.dumps(ledger, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    _write_csv(args.out_dir / "area_footprint.csv", ledger["builds"])
    if args.paper_data_dir:
        args.paper_data_dir.mkdir(parents=True, exist_ok=True)
        _write_csv(args.paper_data_dir / "area_footprint.csv", ledger["builds"])
    readme = """# Candidate10 area footprint

This ledger reports complete routed U55C accelerator resource counts and an
explicitly partial 32 nm SRAM-capacity-equivalent projection for allocated
BRAM/URAM. The projected mm2 column is not full accelerator ASIC area: it
excludes logic, DSPs, interconnect, clocking, I/O, and macro-layout effects.

```bash
python3 scripts/analyze_area_projection.py \\
  --out-dir /tmp/candidate10-area \\
  --paper-data-dir /tmp/candidate10-paper-data
```
"""
    (args.out_dir / "README.md").write_text(readme, encoding="utf-8")
    lines = []
    for output in sorted(args.out_dir.iterdir()):
        if output.is_file() and output.name != "SHA256SUMS":
            lines.append(
                f"{hashlib.sha256(output.read_bytes()).hexdigest()}  {output.name}"
            )
    (args.out_dir / "SHA256SUMS").write_text("\n".join(lines) + "\n", encoding="utf-8")
    print("PASS routed FPGA footprint + partial SRAM area projection")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
