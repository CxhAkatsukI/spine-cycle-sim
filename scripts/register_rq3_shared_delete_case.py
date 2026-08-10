#!/usr/bin/env python3
"""Register a shared-comparison dynamic delete run as an RQ3 case result."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any


DEFAULT_LIB_DIR = Path("/home/chuxiao/spine-cycle-sim-publication/build/sst")


def sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def require_pass(shared_run: dict[str, Any], result: dict[str, Any]) -> None:
    row = shared_run.get("row", {})
    failed = []
    if shared_run.get("status") != "PASS":
        failed.append("shared_status")
    if result.get("success") is not True:
        failed.append("result_success")
    if int(result.get("correctness_mismatches", -1)) != 0:
        failed.append("combined_correctness")
    if int(result.get("architecture_correctness_mismatches", -1)) != 0:
        failed.append("architecture_correctness")
    if int(result.get("mathematical_correctness_mismatches", -1)) != 0:
        failed.append("mathematical_correctness")
    if row.get("measurement_window") != "dynamic_e2e_to_convergence":
        failed.append("measurement_window")
    if row.get("algorithm") != "weighted_dynamic_sssp":
        failed.append("algorithm")
    if failed:
        raise ValueError(f"shared delete run is not RQ3-admissible: {failed}")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--shared-run-dir", type=Path, required=True)
    parser.add_argument("--out-dir", type=Path, required=True)
    parser.add_argument(
        "--execution-id",
        default="rq3_shared_delete_fallback_weighted_sssp",
    )
    parser.add_argument("--role", default="synthetic_calibration")
    parser.add_argument("--lib-dir", type=Path, default=DEFAULT_LIB_DIR)
    args = parser.parse_args()

    shared_run_path = args.shared_run_dir / "shared_run.json"
    result_path = args.shared_run_dir / "result.json"
    shared_run = json.loads(shared_run_path.read_text(encoding="utf-8"))
    result = json.loads(result_path.read_text(encoding="utf-8"))
    require_pass(shared_run, result)

    row = shared_run["row"]
    args.out_dir.mkdir(parents=True, exist_ok=True)
    plugin = args.lib_dir.resolve() / "libspine_cycle.so"
    if not plugin.is_file():
        raise FileNotFoundError(plugin)

    case_result = {
        "status": "pass",
        "case": {
            "execution_id": args.execution_id,
            "dataset_id": str(row["fixture_id"]),
            "system": "spine",
            "algorithm": "weighted_sssp",
            "scenario": "delete",
            "batch_size": int(row["updates"]),
            "source": 0,
            "update": {
                "user_mutations": int(row["updates"]),
                "physical_records": int(row["updates"]),
            },
        },
        "row": {
            "cycles": int(row["cycles"]),
            "dataset_kind": str(row["dataset_kind"]),
            "measurement_window": str(row["measurement_window"]),
            "architecture_correctness_mismatches": int(
                row["architecture_correctness_mismatches"]
            ),
            "mathematical_correctness_mismatches": int(
                row["mathematical_correctness_mismatches"]
            ),
        },
        "scalar_metrics": {
            "measurement_window": str(row["measurement_window"]),
            "maintenance_cycles": int(result.get("maintenance_cycles", 0)),
            "update_cycles": int(result.get("update_cycles", 0)),
        },
        "raw_result_path": str(result_path.resolve()),
        "raw_result_sha256": sha256_file(result_path),
        "shared_run_path": str(shared_run_path.resolve()),
        "shared_run_sha256": sha256_file(shared_run_path),
        "plugin_sha256": sha256_file(plugin),
        "rq3_role": str(args.role),
    }
    output = args.out_dir / "case_result.json"
    output.write_text(
        json.dumps(case_result, indent=2, sort_keys=True) + "\n",
        encoding="ascii",
    )
    print(f"PASS RQ3 shared-delete registration: {output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
