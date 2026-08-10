#!/usr/bin/env python3
"""Verify and summarize the routed refactor31 direct-FPGA evidence."""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
from pathlib import Path
import sys
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from spine_cycle_sim.alignment_contract import load_alignment_contract
from spine_cycle_sim.calibration.refactor31 import (
    load_refactor31_fpga_logs,
    summarize_refactor31_fpga_runs,
)


DEFAULT_CONTRACT = (
    ROOT / "configs/contracts/spine_paper_architecture_alignment_v1.json"
)
DEFAULT_PROFILE = (
    ROOT / "configs/architectures/spine_refactor31_routed_native_v1.json"
)
DEFAULT_MANIFEST = (
    ROOT / "configs/evidence/spine_refactor31_routed_baseline_v1.json"
)


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _write_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    if not rows:
        raise ValueError(f"refusing to write empty CSV {path}")
    fieldnames: list[str] = []
    for row in rows:
        for field in row:
            if field not in fieldnames:
                fieldnames.append(field)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--contract", type=Path, default=DEFAULT_CONTRACT)
    parser.add_argument("--profile", type=Path, default=DEFAULT_PROFILE)
    parser.add_argument("--manifest", type=Path, default=DEFAULT_MANIFEST)
    parser.add_argument("--out-dir", type=Path, required=True)
    args = parser.parse_args()

    contract = load_alignment_contract(args.contract)
    profile = json.loads(args.profile.read_text(encoding="utf-8"))
    manifest = json.loads(args.manifest.read_text(encoding="utf-8"))
    if manifest["architecture_contract_id"] != contract.contract_id:
        raise ValueError("evidence manifest contract ID mismatch")
    if manifest["architecture_contract_sha256"] != contract.sha256:
        raise ValueError("evidence manifest contract hash mismatch")
    if profile["parameters"]["architecture_contract_sha256"] != contract.sha256:
        raise ValueError("refactor31 profile contract hash mismatch")

    kernel_clock_mhz = float(
        next(
            clock["achieved_mhz"]
            for clock in profile["clocks"]
            if clock["name"] == "kernel"
        )
    )
    expected_clock = float(manifest["build"]["achieved_frequency_mhz"])
    if kernel_clock_mhz != expected_clock:
        raise ValueError("profile and routed artifact clock mismatch")

    log_paths: list[Path] = []
    verified_artifacts: list[dict[str, str]] = []
    for artifact in manifest["artifacts"]:
        path = Path(artifact["path"])
        actual = _sha256(path)
        if actual != artifact["sha256"]:
            raise ValueError(f"artifact hash mismatch: {path}")
        verified_artifacts.append(
            {"kind": artifact["kind"], "path": str(path), "sha256": actual}
        )
        if artifact["kind"].startswith("fpga_") and artifact["kind"].endswith(
            "log"
        ):
            log_paths.append(path)

    records = load_refactor31_fpga_logs(log_paths, clock_mhz=kernel_clock_mhz)
    required_repeats = int(contract.payload["validation"]["fpga_repeats_per_case"])
    summaries = summarize_refactor31_fpga_runs(
        records, required_repeats=required_repeats
    )
    run_rows = [record.to_row() for record in records]
    output = args.out_dir.resolve()
    output.mkdir(parents=True, exist_ok=True)
    _write_csv(output / "refactor31_fpga_runs.csv", run_rows)
    _write_csv(output / "refactor31_fpga_case_summary.csv", summaries)

    report = {
        "schema_version": 1,
        "evidence_id": "refactor31_fpga_calibration_analysis_v1",
        "architecture_contract_id": contract.contract_id,
        "architecture_contract_sha256": contract.sha256,
        "profile_id": profile["profile_id"],
        "profile_sha256": _sha256(args.profile),
        "manifest_sha256": _sha256(args.manifest),
        "kernel_clock_mhz": kernel_clock_mhz,
        "verified_artifacts": verified_artifacts,
        "run_count": len(records),
        "case_count": len(summaries),
        "timing_admitted_runs": sum(record.timing_admitted for record in records),
        "correctness_admitted_runs": sum(
            record.correctness_admitted for record in records
        ),
        "calibration_admitted_cases": sum(
            int(row["calibration_admitted"]) for row in summaries
        ),
        "claim_boundary": {
            "supported": [
                "routed_refactor31_execution_timing",
                "exact_and_fallback_path_timing_separation",
                "repeat_stability_for_two_fallback_cases",
            ],
            "not_yet_supported": [
                "algorithm_correctness_gated_cycle_calibration",
                "five_repeat_calibration_gate",
                "medium_real_slice_transfer",
                "paper_aligned_scheduler_calibration",
            ],
        },
    }
    (output / "refactor31_fpga_calibration_evidence.json").write_text(
        json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    print(
        f"runs={len(records)} cases={len(summaries)} "
        f"correctness_admitted={report['correctness_admitted_runs']} "
        f"final_calibration_cases={report['calibration_admitted_cases']}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

