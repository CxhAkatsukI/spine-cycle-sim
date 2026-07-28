#!/usr/bin/env python3
"""Validate and export routed hierarchy component-power attribution."""

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

from spine_cycle_sim.evidence.component_power import (  # noqa: E402
    COMPONENT_ORDER,
    analyze_component_power_manifest,
)


def _write_csv(path: Path, rows: list[dict[str, object]]) -> None:
    with path.open("w", encoding="utf-8", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=list(rows[0]), lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)


def _hashes(out_dir: Path) -> None:
    lines = []
    for path in sorted(out_dir.iterdir()):
        if path.is_file() and path.name != "SHA256SUMS":
            lines.append(f"{hashlib.sha256(path.read_bytes()).hexdigest()}  {path.name}")
    (out_dir / "SHA256SUMS").write_text("\n".join(lines) + "\n", encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--manifest",
        type=Path,
        default=ROOT / "configs/evidence/candidate10_vivado_component_power_v1.json",
    )
    parser.add_argument("--out-dir", type=Path, required=True)
    parser.add_argument("--paper-data-dir", type=Path)
    args = parser.parse_args()

    ledger = analyze_component_power_manifest(args.manifest)
    rows = []
    child_rows = []
    for build in ledger["builds"]:
        rows.append(
            {
                "build_id": build["build_id"],
                "label": build["label"],
                "system": build["system"],
                "algorithm": build["algorithm"],
                "dynamic_w": build["dynamic_w"],
                "device_static_w": build["device_static_w"],
                "ulp_power_w": build["ulp_power_w"],
                "platform_dynamic_residual_w": build["platform_dynamic_residual_w"],
                **build["components_w"],
            }
        )
        child_rows.extend(
            {
                "build_id": build["build_id"],
                **child,
            }
            for child in build["ulp_children"]
        )
    args.out_dir.mkdir(parents=True, exist_ok=True)
    (args.out_dir / "component_power_ledger.json").write_text(
        json.dumps(ledger, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    _write_csv(args.out_dir / "component_power.csv", rows)
    _write_csv(args.out_dir / "ulp_child_power.csv", child_rows)
    if args.paper_data_dir:
        args.paper_data_dir.mkdir(parents=True, exist_ok=True)
        _write_csv(args.paper_data_dir / "component_power.csv", rows)
    readme = """# Candidate10 routed hierarchy component power

All four builds pass source-hash, hierarchy-closure, and frozen-value checks.
The CSV groups direct ULP children without double counting nested hierarchy
rows. Values are Vivado vectorless estimates with `Low` confidence: they
support component attribution and implementation feasibility, not workload
energy or board-power claims.

```bash
python3 scripts/analyze_vivado_component_power.py \\
  --out-dir /tmp/candidate10-component-power \\
  --paper-data-dir /tmp/candidate10-paper-data
```
"""
    (args.out_dir / "README.md").write_text(readme, encoding="utf-8")
    _hashes(args.out_dir)
    print(f"PASS routed hierarchy component power: builds={len(rows)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
