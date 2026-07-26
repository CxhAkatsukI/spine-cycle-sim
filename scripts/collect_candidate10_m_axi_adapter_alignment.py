#!/usr/bin/env python3
"""Collect frozen RTL, SST A/B, and hardware evidence for Candidate10 AXI."""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
from pathlib import Path
from statistics import median


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_ORACLE = (
    ROOT / "docs/evidence/candidate10_m_axi_adapter_rtl_oracle_20260726"
)
DEFAULT_BEFORE = (
    ROOT / "results/candidate10_l0_writer_rtl_schedule_hw_matrix_20260726"
)
DEFAULT_AFTER = (
    ROOT / "results/candidate10_m_axi_adapter_hw_matrix_stats_20260726"
)

LOGICAL_LEDGER_FIELDS = (
    "maintenance_memory_requests_issued",
    "maintenance_sorted_read_bytes",
    "maintenance_persistent_read_bytes",
    "maintenance_persistent_write_bytes",
    "maintenance_metadata_read_bytes",
    "maintenance_metadata_write_bytes",
    "maintenance_graph_read_bytes",
    "maintenance_graph_write_bytes",
    "maintenance_result_write_bytes",
)

AXI_STAT_FIELDS = (
    "maintenance_axi_requests_accepted",
    "maintenance_axi_requests_completed",
    "maintenance_axi_bursts_accepted",
    "maintenance_axi_beats_issued",
    "maintenance_axi_beats_completed",
    "maintenance_axi_address_pipeline_stall_cycles",
    "maintenance_axi_write_burst_serialization_stall_cycles",
    "maintenance_axi_backend_submit_stall_cycles",
    "maintenance_axi_request_queue_stall_cycles",
    "maintenance_axi_response_queue_stall_cycles",
    "maintenance_axi_read_reorder_stall_cycles",
    "maintenance_axi_four_kib_splits",
    "maintenance_axi_max_outstanding_bursts",
    "maintenance_axi_read_bytes",
    "maintenance_axi_write_bytes",
)


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def read_csv(path: Path) -> list[dict[str, str]]:
    with path.open(encoding="utf-8", newline="") as stream:
        return list(csv.DictReader(stream))


def read_json(path: Path) -> dict[str, object]:
    return json.loads(path.read_text(encoding="utf-8"))


def summarize_oracle(path: Path) -> dict[str, object]:
    manifest_path = path / "manifest.json"
    csv_path = path / "m_axi_adapter_oracle.csv"
    manifest = read_json(manifest_path)
    rows = read_csv(csv_path)
    if not manifest.get("all_pass") or len(rows) != manifest.get("cases"):
        raise RuntimeError("m_axi RTL oracle manifest is incomplete")
    if any(row["status"] != "PASS" or int(row["errors"]) != 0 for row in rows):
        raise RuntimeError("m_axi RTL oracle contains a failing case")
    profile = manifest["adapter_profile"]
    if (
        profile["max_read_burst_beats"] != 16
        or profile["max_write_burst_beats"] != 16
        or profile["read_outstanding"] != 16
        or profile["write_outstanding"] != 16
    ):
        raise RuntimeError("m_axi RTL oracle profile diverged from Candidate10")
    return {
        "cases": len(rows),
        "all_pass": True,
        "read_cases": sum(int(row["op"]) == 0 for row in rows),
        "write_cases": sum(int(row["op"]) == 1 for row in rows),
        "backpressure_cases": sum(
            row["expect_backpressure"].lower() == "true" for row in rows
        ),
        "outstanding_limit_cases": sum(
            row["expect_outstanding_limit"].lower() == "true" for row in rows
        ),
        "max_observed_outstanding": max(
            int(row["max_outstanding"]) for row in rows
        ),
        "adapter_profile": profile,
        "rtl_member": manifest["rtl_member"],
        "rtl_member_sha256": manifest["rtl_member_sha256"],
        "xo_sha256": manifest["xo_sha256"],
        "manifest_sha256": sha256(manifest_path),
        "oracle_csv_sha256": sha256(csv_path),
    }


def _rows_by_case(path: Path) -> dict[str, dict[str, str]]:
    rows = read_csv(path)
    if any(row["status"] != "PASS" for row in rows):
        raise RuntimeError(f"matrix contains a failing row: {path}")
    result = {row["case_id"]: row for row in rows}
    if len(result) != len(rows):
        raise RuntimeError(f"matrix contains duplicate case IDs: {path}")
    return result


def compare_matrices(before_dir: Path, after_dir: Path) -> dict[str, object]:
    before_path = before_dir / "matrix.csv"
    after_path = after_dir / "matrix.csv"
    before = _rows_by_case(before_path)
    after = _rows_by_case(after_path)
    if set(before) != set(after):
        raise RuntimeError("before/after matrices do not contain the same cases")

    cases: list[dict[str, object]] = []
    grouped: dict[str, dict[str, list[float]]] = {}
    for case_id, new in after.items():
        old = before[case_id]
        for field in (
            "evidence_case",
            "role",
            "vertices",
            "input_edges",
            "hardware_cycles",
            "slice_sha256",
        ):
            if old[field] != new[field]:
                raise RuntimeError(f"{case_id}: matrix field changed: {field}")
        old_summary = read_json(before_dir / "runs" / case_id / "summary.json")
        new_summary = read_json(after_dir / "runs" / case_id / "summary.json")
        if not old_summary.get("success") or not new_summary.get("success"):
            raise RuntimeError(f"{case_id}: simulator run did not pass")
        if new_summary.get("spine_axi_profile") != "candidate10_gmem_1e61fc0":
            raise RuntimeError(f"{case_id}: Candidate10 AXI profile was not active")
        expected_profile = {
            "axi_maintenance_readwrite_max_pending_requests": 70,
            "axi_maintenance_writeonly_max_pending_requests": 67,
            "axi_read_reorder_capacity": 256,
            "axi_read_address_pipeline_cycles": 7,
            "axi_write_buffer_pipeline_cycles": 10,
            "axi_serialize_write_bursts": True,
            "axi_maintenance_result_data_width_bytes": 8,
        }
        for field, expected in expected_profile.items():
            if new_summary.get(field) != expected:
                raise RuntimeError(f"{case_id}: profile field mismatch: {field}")
        for field in LOGICAL_LEDGER_FIELDS:
            if old_summary.get(field) != new_summary.get(field):
                raise RuntimeError(f"{case_id}: logical ledger changed: {field}")
        for field in AXI_STAT_FIELDS:
            if field not in new_summary:
                raise RuntimeError(f"{case_id}: missing AXI statistic: {field}")
        if (
            new_summary["maintenance_axi_requests_accepted"]
            != new_summary["maintenance_axi_requests_completed"]
            or new_summary["maintenance_axi_beats_issued"]
            != new_summary["maintenance_axi_beats_completed"]
            or new_summary["maintenance_axi_max_outstanding_bursts"] > 16
        ):
            raise RuntimeError(f"{case_id}: AXI request/beat ledger did not close")

        old_error = float(old["raw_error_pct"])
        new_error = float(new["raw_error_pct"])
        role = new["role"]
        values = grouped.setdefault(role, {"before": [], "after": []})
        values["before"].append(abs(old_error))
        values["after"].append(abs(new_error))
        cases.append(
            {
                "case_id": case_id,
                "role": role,
                "input_edges": int(new["input_edges"]),
                "hardware_cycles": float(new["hardware_cycles"]),
                "before_cycles": int(old["simulated_cycles"]),
                "after_cycles": int(new["simulated_cycles"]),
                "cycle_delta": int(new["simulated_cycles"])
                - int(old["simulated_cycles"]),
                "before_error_pct": old_error,
                "after_error_pct": new_error,
                "absolute_error_improvement_pct_points": abs(old_error)
                - abs(new_error),
                "backend_requests_before": int(old["backend_requests"]),
                "backend_requests_after": int(new["backend_requests"]),
                "logical_ledger": {
                    field: new_summary[field] for field in LOGICAL_LEDGER_FIELDS
                },
                "axi_stats": {
                    field: new_summary[field] for field in AXI_STAT_FIELDS
                },
            }
        )

    summaries = {}
    for role, values in sorted(grouped.items()):
        before_median = median(values["before"])
        after_median = median(values["after"])
        summaries[role] = {
            "cases": len(values["after"]),
            "before_median_abs_error_pct": before_median,
            "after_median_abs_error_pct": after_median,
            "median_abs_error_improvement_pct_points": (
                before_median - after_median
            ),
            "after_max_abs_error_pct": max(values["after"]),
        }
    return {
        "cases": cases,
        "group_summary": summaries,
        "before_matrix_sha256": sha256(before_path),
        "after_matrix_sha256": sha256(after_path),
    }


def collect(
    oracle_dir: Path, before_dir: Path, after_dir: Path
) -> dict[str, object]:
    return {
        "schema_version": 1,
        "claim": "candidate10_m_axi_adapter_execution_alignment",
        "rtl_oracle": summarize_oracle(oracle_dir),
        "hardware_holdout": compare_matrices(before_dir, after_dir),
        "claim_boundary": {
            "modeled": [
                "64-bit child word address to AXI byte address conversion",
                "16-beat and 4-KiB burst splitting",
                "read-address and write-buffer adapter pipelines",
                "16 outstanding bursts, 256-beat read reorder capacity",
                "ordered write-burst issue and finite FIFO backpressure",
                "Candidate10 maintenance adapter request capacities and result width",
            ],
            "remaining": [
                "kernel wrapper and ap_ctrl launch/finish fixed schedule",
                "full inter-port U55C AXI crossbar arbitration",
                "measured HBM controller timing calibration",
                "compute-XO adapter equivalence beyond inherited source shape",
            ],
        },
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--oracle-dir", type=Path, default=DEFAULT_ORACLE)
    parser.add_argument("--before-dir", type=Path, default=DEFAULT_BEFORE)
    parser.add_argument("--after-dir", type=Path, default=DEFAULT_AFTER)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    evidence = collect(
        args.oracle_dir.resolve(),
        args.before_dir.resolve(),
        args.after_dir.resolve(),
    )
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(
        json.dumps(evidence, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    summary = evidence["hardware_holdout"]["group_summary"]
    print(
        "PASS candidate10_m_axi_adapter_alignment: "
        f"rtl={evidence['rtl_oracle']['cases']} "
        f"cal={summary['calibration']['after_median_abs_error_pct']:.2f}% "
        f"holdout={summary['holdout']['after_median_abs_error_pct']:.2f}%"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
