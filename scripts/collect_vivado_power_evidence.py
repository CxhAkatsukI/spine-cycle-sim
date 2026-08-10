#!/usr/bin/env python3
"""Export hashed, explicitly scoped Vivado implementation-power evidence."""

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

from spine_cycle_sim.evidence.vivado_power import parse_vivado_power_log  # noqa: E402


def _write_csv(path: Path, rows: list[dict[str, object]]) -> None:
    with path.open("w", encoding="utf-8", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=list(rows[0]), lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)


def _write_hashes(out_dir: Path) -> None:
    lines = []
    for path in sorted(out_dir.iterdir()):
        if path.is_file() and path.name != "SHA256SUMS":
            lines.append(f"{hashlib.sha256(path.read_bytes()).hexdigest()}  {path.name}")
    (out_dir / "SHA256SUMS").write_text("\n".join(lines) + "\n", encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--log", type=Path, required=True)
    parser.add_argument("--out-dir", type=Path, required=True)
    parser.add_argument("--label", default="Spine opt-v2")
    parser.add_argument(
        "--generic-components",
        action="store_true",
        help="parse the complete hierarchy without requiring Spine-specific names",
    )
    args = parser.parse_args()

    ledger = parse_vivado_power_log(
        args.log,
        required_components={} if args.generic_components else None,
    )
    args.out_dir.mkdir(parents=True, exist_ok=True)
    (args.out_dir / "power_summary.json").write_text(
        json.dumps(ledger, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    _write_csv(args.out_dir / "power_hierarchy.csv", ledger["hierarchy"])
    if ledger["publication_components"]:
        _write_csv(
            args.out_dir / "publication_components.csv",
            ledger["publication_components"],
        )
    summary = ledger["summary"]
    readme = f"""# {args.label} Vivado power evidence

- Status: `{ledger['status']}`
- Claim class: `{ledger['claim_class']}`
- Total on-chip: `{summary['total_on_chip_w']:.3f} W`
- Dynamic: `{summary['dynamic_w']:.3f} W`
- Device static: `{summary['device_static_w']:.3f} W`
- FPGA / HBM: `{summary['fpga_w']:.3f} / {summary['hbm_w']:.3f} W`
- Activity confidence: `{summary['confidence_level']}`
- Simulation activity file: `{summary['simulation_activity_file']}`

These values come from Vivado's automatic vectorless post-route report. They
support implementation feasibility and component attribution; they are not
used as workload-calibrated energy. See `power_summary.json` for the hashed
source identity and the complete limitation ledger.
"""
    (args.out_dir / "README.md").write_text(readme, encoding="utf-8")
    _write_hashes(args.out_dir)
    print(json.dumps({"status": "PASS", "out_dir": str(args.out_dir)}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
