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
        rows.append(
            {
                "build_id": build["build_id"],
                "system": build["system"],
                "algorithm": build["algorithm"],
                "claim_scope": build["claim_scope"],
                **{key: build["resources"][key] for key in RESOURCE_KEYS},
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


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", type=Path, default=DEFAULT_MANIFEST)
    parser.add_argument("--out-dir", type=Path, required=True)
    args = parser.parse_args()

    ledger = analyze_publication_ppa_manifest(args.manifest)
    args.out_dir.mkdir(parents=True, exist_ok=True)
    (args.out_dir / "ppa_ledger.json").write_text(
        json.dumps(ledger, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    _write_csv(args.out_dir / "ppa_summary.csv", _summary_rows(ledger))
    print(
        "PASS Candidate10 routed HLS feasibility: "
        f"builds={len(ledger['builds'])} "
        "resource_ratio_eligible=false"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
