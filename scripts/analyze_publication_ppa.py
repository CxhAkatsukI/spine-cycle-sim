#!/usr/bin/env python3
"""Validate and export Candidate10 routed-HLS feasibility evidence."""

from __future__ import annotations

import argparse
import csv
import json
from pathlib import Path
import sys


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from spine_cycle_sim.evidence.publication_ppa import (  # noqa: E402
    RESOURCE_KEYS,
    analyze_publication_ppa_manifest,
)


DEFAULT_MANIFEST = ROOT / "configs/evidence/candidate10_publication_ppa_v3.json"


def _write_csv(path: Path, rows: list[dict[str, object]]) -> None:
    if not rows:
        raise ValueError(f"refusing to write empty CSV: {path}")
    with path.open("w", encoding="utf-8", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=list(rows[0]), lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)


def _summary_rows(ledger: dict[str, object]) -> list[dict[str, object]]:
    rows = []
    for build in ledger["builds"]:
        timing = build["timing"]
        topology = build["topology"]
        rows.append(
            {
                "build_id": build["build_id"],
                "system": build["system"],
                "algorithm": build["algorithm"],
                "claim_scope": build["claim_scope"],
                **{key: build["resources"][key] for key in RESOURCE_KEYS},
                "kernel_kinds": len(topology["kernels"]),
                "kernel_cus": sum(topology["kernels"].values()),
                "hbm_channels": json.dumps(
                    topology["hbm_channels"], separators=(",", ":")
                ),
                "hbm_port_bindings": topology["hbm_port_bindings"],
                "stream_connections": topology["stream_connections"],
                "slr_assignments": topology["slr_assignments"],
                "target_mhz": build["target_mhz"],
                "wns_ns": timing["wns_ns"],
                "tns_ns": timing["tns_ns"],
                "setup_failing_endpoints": timing["failing_endpoints"],
                "timing_disposition": timing["disposition"],
                "worst_path_frequency_mhz": timing["worst_path_frequency_mhz"],
                "xclbin_sha256": build["artifact"]["sha256"],
            }
        )
    return rows


def _paper_rows(ledger: dict[str, object]) -> list[dict[str, object]]:
    labels = {
        "spine_candidate10_sssp_152mhz": "Spine SSSP",
        "grasu_regraph_weighted_sssp_150mhz": "G+R SSSP",
        "grasu_regraph_full_pagerank_150mhz": "G+R Full PR",
        "grasu_regraph_thresholded_residual_pagerank_150mhz": "G+R Residual PR",
    }
    rows = []
    for build in ledger["builds"]:
        timing = build["timing"]
        rows.append(
            {
                "label": labels[build["build_id"]],
                "target_mhz": build["target_mhz"],
                "lut": build["resources"]["lut"],
                "reg": build["resources"]["reg"],
                "bram": build["resources"]["bram"],
                "uram": build["resources"]["uram"],
                "dsp": build["resources"]["dsp"],
                "wns_ns": timing["wns_ns"],
                "timing": (
                    "closed"
                    if timing["disposition"] == "target_closed"
                    else "target missed"
                ),
            }
        )
    return rows


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", type=Path, default=DEFAULT_MANIFEST)
    parser.add_argument("--out-dir", type=Path, required=True)
    parser.add_argument(
        "--paper-data-dir",
        type=Path,
        help="Also write the compact TeX-facing PPA table to this directory.",
    )
    args = parser.parse_args()

    ledger = analyze_publication_ppa_manifest(args.manifest)
    args.out_dir.mkdir(parents=True, exist_ok=True)
    (args.out_dir / "ppa_ledger.json").write_text(
        json.dumps(ledger, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    _write_csv(args.out_dir / "ppa_summary.csv", _summary_rows(ledger))
    if args.paper_data_dir:
        args.paper_data_dir.mkdir(parents=True, exist_ok=True)
        _write_csv(args.paper_data_dir / "ppa_summary.csv", _paper_rows(ledger))
    print(
        "PASS Candidate10 routed HLS feasibility: "
        f"builds={len(ledger['builds'])} "
        "resource_ratio_eligible=false"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
