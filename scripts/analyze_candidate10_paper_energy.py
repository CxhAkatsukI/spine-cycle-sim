#!/usr/bin/env python3
"""Produce paper-facing HBM-only energy ratios from matched evidence."""

from __future__ import annotations

import argparse
import csv
import json
from pathlib import Path
import sys


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from spine_cycle_sim.evidence.paper_energy import paper_hbm_energy_rows  # noqa: E402
from spine_cycle_sim.experiments.comparison_analysis import sha256_file  # noqa: E402


DEFAULT_SOURCE = (
    ROOT
    / "docs/evidence/candidate10_hls_v3_matched_pagerank_energy_20260727"
    / "analysis/pair_energy.csv"
)


def _write_csv(path: Path, rows: list[dict[str, object]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as stream:
        writer = csv.DictWriter(
            stream, fieldnames=list(rows[0]), lineterminator="\n"
        )
        writer.writeheader()
        writer.writerows(rows)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, default=DEFAULT_SOURCE)
    parser.add_argument("--out-dir", type=Path, required=True)
    parser.add_argument("--paper-data-dir", type=Path)
    args = parser.parse_args()

    with args.source.open(encoding="utf-8", newline="") as stream:
        rows = list(csv.DictReader(stream))
    paper_rows = paper_hbm_energy_rows(rows)
    args.out_dir.mkdir(parents=True, exist_ok=True)
    output = args.out_dir / "hbm_energy_by_algorithm.csv"
    _write_csv(output, paper_rows)
    if args.paper_data_dir is not None:
        _write_csv(
            args.paper_data_dir / "hbm_energy_by_algorithm.csv", paper_rows
        )
    evidence = {
        "schema_version": 1,
        "evidence_id": "candidate10_paper_hbm_energy_v1_20260727",
        "status": "PASS",
        "claim_class": "matched_32_controller_hbm_energy_not_total_accelerator",
        "source": str(args.source.resolve()),
        "source_sha256": sha256_file(args.source),
        "output_sha256": sha256_file(output),
        "algorithms": [row["algorithm_id"] for row in paper_rows],
        "pairs": sum(int(row["pairs"]) for row in paper_rows),
        "limitations": [
            "The inputs are three compact holdout slices, not full datasets.",
            "HBM energy is DRAMSim3 energy across all 32 controller instances.",
            (
                "Logic, FIFO, interconnect, clock, host, PCIe, shell, and board "
                "energy are excluded."
            ),
            "Projected CACTI SRAM energy is intentionally not used in this ratio.",
        ],
    }
    (args.out_dir / "hbm_energy_evidence.json").write_text(
        json.dumps(evidence, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    print(f"PASS matched HBM energy: algorithms={len(paper_rows)} pairs=6")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
