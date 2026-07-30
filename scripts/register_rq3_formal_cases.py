#!/usr/bin/env python3
"""Register standalone zero-net and residual runs as RQ3 case results."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any


def sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def require_correct(result: dict[str, Any], label: str) -> None:
    checks = {
        "success": result.get("success") is True,
        "architecture_oracle": bool(result.get("architecture_oracle")),
        "mathematical_oracle": bool(result.get("mathematical_oracle")),
        "architecture_correctness": result.get("architecture_correctness_mismatches") == 0,
        "mathematical_correctness": result.get("mathematical_correctness_mismatches") == 0,
        "combined_correctness": result.get("correctness_mismatches") == 0,
    }
    failed = [name for name, passed in checks.items() if not passed]
    if failed:
        raise ValueError(f"{label} failed RQ3 correctness admission: {failed}")


def write_case_result(
    destination: Path,
    *,
    execution_id: str,
    dataset_id: str,
    algorithm: str,
    scenario: str,
    batch_size: int,
    physical_records: int,
    raw_path: Path,
    result: dict[str, Any],
    plugin_sha256: str,
    role: str,
) -> dict[str, Any]:
    destination.mkdir(parents=True, exist_ok=True)
    payload = {
        "status": "pass",
        "case": {
            "execution_id": execution_id,
            "dataset_id": dataset_id,
            "system": "spine",
            "algorithm": algorithm,
            "scenario": scenario,
            "batch_size": batch_size,
            "update": {
                "user_mutations": batch_size,
                "physical_records": physical_records,
            },
        },
        "row": {
            "cycles": int(result["cycles"]),
            "dataset_kind": "synthetic" if role == "synthetic_calibration" else "real",
            "architecture_correctness_mismatches": 0,
            "mathematical_correctness_mismatches": 0,
        },
        "scalar_metrics": {
            "maintenance_cycles": int(result.get("maintenance_cycles", 0)),
            "update_mode": result.get("update_mode", ""),
        },
        "raw_result_path": str(raw_path.resolve()),
        "raw_result_sha256": sha256_file(raw_path),
        "plugin_sha256": plugin_sha256,
        "rq3_role": role,
    }
    output = destination / "case_result.json"
    output.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="ascii")
    return {
        "execution_id": execution_id,
        "case_result_path": str(output.resolve()),
        "case_result_sha256": sha256_file(output),
        "raw_result_path": str(raw_path.resolve()),
        "raw_result_sha256": sha256_file(raw_path),
        "plugin_sha256": plugin_sha256,
        "role": role,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--formal-root", type=Path, required=True)
    args = parser.parse_args()

    cc_dir = args.formal_root / "zero_net_cc"
    cc_path = cc_dir / "result.json"
    cc_manifest_path = cc_dir / "run_manifest.json"
    cc = json.loads(cc_path.read_text(encoding="utf-8"))
    cc_manifest = json.loads(cc_manifest_path.read_text(encoding="utf-8"))
    require_correct(cc, "CC zero-net")
    if (
        cc.get("update_mode") != "zero_net_no_repair"
        or cc_manifest.get("admitted") is not True
        or cc_manifest.get("checks", {}).get("dual_oracle") is not True
    ):
        raise ValueError("CC zero-net lacks admitted no-repair evidence")
    cc_plugin = str(cc_manifest["sst_plugin_sha256"])

    residual_matrix = args.formal_root / "residual_correction" / "summary.json"
    residual_summary = json.loads(residual_matrix.read_text(encoding="utf-8"))
    candidates = [
        row
        for row in residual_summary.get("runs", [])
        if row.get("architecture") == "spine"
        and abs(float(row.get("epsilon", 0.0)) - 1.0e-6) < 1.0e-15
    ]
    if residual_summary.get("all_correct") is not True or len(candidates) != 1:
        raise ValueError("residual correction matrix lacks one admitted Spine row")
    residual_row = candidates[0]
    residual_path = Path(residual_row["result_path"])
    residual = json.loads(residual_path.read_text(encoding="utf-8"))
    require_correct(residual, "residual correction")
    if (
        residual.get("residual_contract") != "deltahls_sink_free_linf_warm"
        or int(residual.get("reader_edges_total", 0)) <= 0
        or int(residual.get("compute_edges_total", 0)) <= 0
        or residual.get("active_edge_execution_ledger_match") is not True
        or residual.get("memory_ledger_match") is not True
    ):
        raise ValueError("residual correction lacks physical-work closure")
    residual_plugin = str(residual["sst_plugin_sha256"])

    registrations = [
        write_case_result(
            args.formal_root / "runs" / "zero_net",
            execution_id="rq3_zero_net_cc_u2",
            dataset_id="synthetic_cc_zero_net",
            algorithm="connected_components",
            scenario="weight_change",
            batch_size=2,
            physical_records=int(cc["physical_update_records"]),
            raw_path=cc_path,
            result=cc,
            plugin_sha256=cc_plugin,
            role="synthetic_calibration",
        ),
        write_case_result(
            args.formal_root / "runs" / "residual_correction",
            execution_id="rq3_flickr_residual_correction_u8_eps1e6",
            dataset_id="soc_flickr_sinkfree_8192e",
            algorithm="thresholded_residual_pagerank",
            scenario="insert",
            batch_size=int(residual_row["user_mutations"]),
            physical_records=int(residual_row["physical_records"]),
            raw_path=residual_path,
            result=residual,
            plugin_sha256=residual_plugin,
            role="trace_holdout",
        ),
    ]
    registry = {
        "schema_version": 1,
        "registry_id": "rq3_formal_standalone_cases_v1",
        "cc_manifest_sha256": sha256_file(cc_manifest_path),
        "residual_matrix_sha256": sha256_file(residual_matrix),
        "registrations": registrations,
    }
    registry_path = args.formal_root / "registry.json"
    registry_path.write_text(
        json.dumps(registry, indent=2, sort_keys=True) + "\n", encoding="ascii"
    )
    print(f"PASS RQ3 standalone registration: cases={len(registrations)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
