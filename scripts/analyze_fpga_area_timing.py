#!/usr/bin/env python3
"""Extract reproducible routed FPGA area and timing evidence."""

from __future__ import annotations

import argparse
import csv
import json
from pathlib import Path
import sys


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from spine_cycle_sim.evidence.fpga import (  # noqa: E402
    RESOURCE_KEYS,
    analyze_fpga_manifest,
)


DEFAULT_MANIFEST = ROOT / "configs/evidence/fpga_routed_native_20260725.json"


def _summary_rows(ledger: dict[str, object]) -> list[dict[str, object]]:
    rows = []
    for build in ledger["builds"]:
        used = build["utilization"]["used_resources"]
        timing = build["timing"]
        clock = build["xclbin"]["data_clock"]
        row = {
            "build_id": build["build_id"],
            "system": build["system"],
            "role": build["role"],
            "claim_label": build["claim_label"],
            **{resource: used[resource]["count"] for resource in RESOURCE_KEYS},
            "requested_mhz": clock["requested_mhz"],
            "achieved_mhz": clock["achieved_mhz"],
            "packaged_mhz": clock["packaged_mhz"],
            "global_wns_ns": timing["design_summary"]["wns_ns"],
            "global_tns_ns": timing["design_summary"]["tns_ns"],
            "kernel_wns_ns": timing["kernel_clock"]["timing"]["wns_ns"],
            "kernel_tns_ns": timing["kernel_clock"]["timing"]["tns_ns"],
            "requested_constraints_met": timing[
                "constraints_met_at_requested_clock"
            ],
            "timing_disposition": build["timing_disposition"],
        }
        rows.append(row)
    return rows


def _component_rows(ledger: dict[str, object]) -> list[dict[str, object]]:
    rows = []
    for build in ledger["builds"]:
        for component in build["utilization"]["components"]:
            rows.append(
                {
                    "build_id": build["build_id"],
                    "system": build["system"],
                    "component": component["name"],
                    **{
                        resource: component["resources"][resource]["count"]
                        for resource in RESOURCE_KEYS
                    },
                }
            )
    return rows


def _write_csv(path: Path, rows: list[dict[str, object]]) -> None:
    if not rows:
        raise ValueError(f"refusing to write empty CSV: {path}")
    with path.open("w", newline="", encoding="utf-8") as output:
        writer = csv.DictWriter(output, fieldnames=list(rows[0]), lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--manifest", type=Path, default=DEFAULT_MANIFEST)
    parser.add_argument("--out-dir", type=Path, required=True)
    args = parser.parse_args()

    ledger = analyze_fpga_manifest(args.manifest)
    args.out_dir.mkdir(parents=True, exist_ok=True)
    (args.out_dir / "fpga_area_timing.json").write_text(
        json.dumps(ledger, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    _write_csv(args.out_dir / "fpga_summary.csv", _summary_rows(ledger))
    _write_csv(args.out_dir / "fpga_components.csv", _component_rows(ledger))

    print(
        "PASS fpga_area_timing: "
        + " ".join(
            f"{build['build_id']}={build['timing_disposition']}"
            for build in ledger["builds"]
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
