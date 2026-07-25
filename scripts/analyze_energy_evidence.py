#!/usr/bin/env python3
"""Build the frozen DRAMSim3 + CACTI selected-array energy ledger."""

from __future__ import annotations

import argparse
import csv
import json
from pathlib import Path
import sys
import tempfile


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from spine_cycle_sim.evidence.energy import (  # noqa: E402
    analyze_energy_manifest,
    reproduce_cacti_characterizations,
)


DEFAULT_MANIFEST = ROOT / "configs/evidence/onchip_energy_20260725.json"


def _write_csv(path: Path, rows: list[dict[str, object]]) -> None:
    if not rows:
        raise ValueError(f"refusing to write empty CSV: {path}")
    with path.open("w", newline="", encoding="utf-8") as output:
        writer = csv.DictWriter(output, fieldnames=list(rows[0]), lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)


def _run_rows(ledger: dict[str, object]) -> list[dict[str, object]]:
    rows = []
    for run in ledger["runs"]:
        rows.append(
            {
                "run_id": run["run_id"],
                "system": run["system"],
                "profile_id": run["profile_id"],
                "comparison_role": run["comparison_role"],
                "claim_label": run["claim_label"],
                "cycles": run["cycles"],
                "clock_mhz": run["clock_mhz"],
                "runtime_ns": run["runtime_ns"],
                "backend_requests": run["backend_requests"],
                "dram_reads": run["dram"]["reads"],
                "dram_writes": run["dram"]["writes"],
                "dram_energy_pj": run["dram"]["total_energy_pj"],
                "selected_onchip_dynamic_pj": run["selected_onchip"][
                    "dynamic_energy_pj"
                ],
                "selected_onchip_leakage_pj": run["selected_onchip"][
                    "leakage_energy_pj"
                ],
                "selected_onchip_energy_pj": run["selected_onchip"][
                    "total_energy_pj"
                ],
                "selected_onchip_asic_area_mm2": run["selected_onchip"][
                    "projected_asic_sram_area_mm2"
                ],
                "partial_sum_pj": run["partial_energy_ledger"]["sum_pj"],
            }
        )
    return rows


def _array_rows(ledger: dict[str, object]) -> list[dict[str, object]]:
    rows = []
    for run in ledger["runs"]:
        for array in run["selected_onchip"]["arrays"]:
            rows.append(
                {
                    "run_id": run["run_id"],
                    "system": run["system"],
                    "array_id": array["array_id"],
                    "characterization_id": array["characterization_id"],
                    "instances": array["instances"],
                    "reads": array["reads"],
                    "writes": array["writes"],
                    "dynamic_energy_pj": array["dynamic_energy_pj"],
                    "leakage_energy_pj": array["leakage_energy_pj"],
                    "selected_array_energy_pj": array["selected_array_energy_pj"],
                    "projected_asic_sram_area_mm2": array[
                        "projected_asic_sram_area_mm2"
                    ],
                    "claim_label": array["claim_label"],
                }
            )
    return rows


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--manifest", type=Path, default=DEFAULT_MANIFEST)
    parser.add_argument("--out-dir", type=Path, required=True)
    parser.add_argument(
        "--reproduce-cacti",
        action="store_true",
        help="rebuild pinned CACTI-P source and require byte-identical outputs",
    )
    parser.add_argument(
        "--cacti-source-dir",
        type=Path,
        default=Path("/data/feiyang/mcpat/cacti"),
    )
    args = parser.parse_args()

    ledger = analyze_energy_manifest(args.manifest)
    args.out_dir.mkdir(parents=True, exist_ok=True)
    (args.out_dir / "energy_evidence.json").write_text(
        json.dumps(ledger, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    _write_csv(args.out_dir / "energy_runs.csv", _run_rows(ledger))
    _write_csv(args.out_dir / "energy_arrays.csv", _array_rows(ledger))

    if args.reproduce_cacti:
        with tempfile.TemporaryDirectory(prefix="spine-cacti-reproduce-") as tmp:
            reproduction = reproduce_cacti_characterizations(
                args.manifest, args.cacti_source_dir, tmp
            )
        reproduction["build"] = {
            "binary_sha256": reproduction["build"]["binary_sha256"],
            "command": reproduction["build"]["command"],
            "compatibility_patch": reproduction["build"]["compatibility_patch"],
        }
        (args.out_dir / "cacti_reproduction.json").write_text(
            json.dumps(reproduction, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )

    print(
        "PASS energy_evidence: "
        + " ".join(
            f"{run['run_id']}={run['partial_energy_ledger']['sum_pj']:.3f}pJ(partial)"
            for run in ledger["runs"]
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
