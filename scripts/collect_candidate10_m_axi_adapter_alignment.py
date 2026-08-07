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
DEFAULT_INPUTS = ROOT / "docs/evidence/candidate10_alignment_inputs_20260727"
DEFAULT_BEFORE = (
    DEFAULT_INPUTS / "axi_before"
)
DEFAULT_AFTER = (
    DEFAULT_INPUTS / "axi_after"
)
DEFAULT_CORE_LOG = (
    ROOT / "docs/evidence/candidate10_m_axi_adapter_backpressure_20260726/"
    "core_trace.log"
)
CORE_SOURCES = (
    ROOT / "cpp/include/spine_sim/axi.hpp",
    ROOT / "cpp/src/axi.cpp",
    ROOT / "cpp/tests/core_tests.cpp",
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
    "maintenance_axi_write_child_beats_accepted",
    "maintenance_axi_write_child_data_stall_cycles",
    "maintenance_axi_write_store_to_bridge_beats",
    "maintenance_axi_write_bridge_to_throttle_beats",
    "maintenance_axi_write_throttle_data_stall_cycles",
    "maintenance_axi_max_write_store_occupancy",
    "maintenance_axi_max_write_throttle_occupancy",
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


def parse_trace_fields(line: str) -> dict[str, int | str]:
    fields: dict[str, int | str] = {}
    for item in line.split()[1:]:
        key, value = item.split("=", 1)
        try:
            fields[key] = int(value)
        except ValueError:
            fields[key] = value
    return fields


def parse_core_trace(path: Path) -> dict[str, list[dict[str, int | str]]]:
    prefixes = {
        "events": "AXI_CORE_EVENT ",
        "bursts": "AXI_CORE_BURST ",
        "beats": "AXI_CORE_BEAT ",
        "summaries": "AXI_CORE_SUMMARY ",
    }
    result: dict[str, list[dict[str, int | str]]] = {
        key: [] for key in prefixes
    }
    for line in path.read_text(encoding="utf-8").splitlines():
        for key, prefix in prefixes.items():
            if line.startswith(prefix):
                result[key].append(parse_trace_fields(line))
                break
    if len(result["summaries"]) != 2:
        raise RuntimeError("core AXI transcript does not contain two summaries")
    return result


def _cycles(events: list[dict[str, int | str]], kind: str) -> list[int]:
    return [int(event["cycle"]) for event in events if event["kind"] == kind]


def _lasts(events: list[dict[str, int | str]], kind: str) -> list[int]:
    return [int(event.get("last", 0))
            for event in events if event["kind"] == kind]


def _delta_summary(reference: list[int], observed: list[int]) -> dict[str, object]:
    if len(reference) != len(observed):
        raise RuntimeError("AXI event transcript lengths differ")
    deltas = [right - left for left, right in zip(reference, observed)]
    return {
        "events": len(reference),
        "exact_events": sum(delta == 0 for delta in deltas),
        "max_abs_delta_cycles": max(map(abs, deltas), default=0),
        "deltas": deltas,
    }


def compare_backpressure_transcripts(
    oracle_dir: Path, core_log: Path
) -> dict[str, object]:
    rows = {
        row["case_id"]: row
        for row in read_csv(oracle_dir / "m_axi_adapter_oracle.csv")
    }
    core = parse_core_trace(core_log)
    cases: dict[str, object] = {}
    for op, case_id in (
        (0, "read_channel_backpressure"),
        (1, "write_channel_backpressure"),
    ):
        rtl_row = rows[case_id]
        rtl_events = json.loads(rtl_row["event_trace"])
        rtl_bursts = json.loads(rtl_row["burst_trace"])
        core_events = [event for event in core["events"] if event["op"] == op]
        core_bursts = [burst for burst in core["bursts"] if burst["op"] == op]
        core_beats = [beat for beat in core["beats"] if beat["op"] == op]
        core_summary = next(
            summary for summary in core["summaries"] if summary["op"] == op
        )
        core_origin = min(_cycles(core_events, "child_request"))
        core_request_cycles = [
            cycle - core_origin for cycle in _cycles(core_events, "child_request")
        ]
        request_alignment = _delta_summary(
            _cycles(rtl_events, "child_request"), core_request_cycles
        )

        rtl_shape = [
            (int(burst["addr"]), int(burst["beats"])) for burst in rtl_bursts
        ]
        core_shape = [
            (int(burst["addr"]), int(burst["beats"])) for burst in core_bursts
        ]
        if rtl_shape != core_shape:
            raise RuntimeError(f"{case_id}: burst shape differs")
        burst_alignment = _delta_summary(
            [int(burst["issue_cycle"]) for burst in rtl_bursts],
            [int(burst["issue_cycle"]) - core_origin for burst in core_bursts],
        )

        if op == 0:
            external_alignment = _delta_summary(
                _cycles(rtl_events, "external_data"),
                [int(beat["completion_cycle"]) - core_origin
                 for beat in core_beats],
            )
            child_alignment = _delta_summary(
                _cycles(rtl_events, "child_data"),
                [cycle - core_origin
                 for cycle in _cycles(core_events, "child_data")],
            )
            external_response_alignment = None
            bridge_last_markers_exact = None
        else:
            external_alignment = _delta_summary(
                _cycles(rtl_events, "external_data"),
                [int(beat["issue_cycle"]) - core_origin for beat in core_beats],
            )
            child_alignment = _delta_summary(
                _cycles(rtl_events, "child_response"),
                [cycle - core_origin
                 for cycle in _cycles(core_events, "child_response")],
            )
            core_burst_completions: list[int] = []
            cursor = 0
            for burst in core_bursts:
                cursor += int(burst["beats"])
                core_burst_completions.append(
                    int(core_beats[cursor - 1]["completion_cycle"]) - core_origin
                )
            external_response_alignment = _delta_summary(
                _cycles(rtl_events, "external_response"),
                core_burst_completions,
            )
            child_write_alignment = _delta_summary(
                _cycles(rtl_events, "child_data"),
                [cycle - core_origin
                 for cycle in _cycles(core_events, "child_data")],
            )
            store_bridge_alignment = _delta_summary(
                _cycles(rtl_events, "internal_store_to_bridge"),
                [cycle - core_origin for cycle in _cycles(
                    core_events, "internal_store_to_bridge"
                )],
            )
            bridge_throttle_alignment = _delta_summary(
                _cycles(rtl_events, "internal_bridge_to_throttle"),
                [cycle - core_origin for cycle in _cycles(
                    core_events, "internal_bridge_to_throttle"
                )],
            )
            if _lasts(rtl_events, "internal_bridge_to_throttle") != _lasts(
                core_events, "internal_bridge_to_throttle"
            ):
                raise RuntimeError(
                    f"{case_id}: throttle burst-last markers differ"
                )
            bridge_last_markers_exact = True
        if op == 0:
            child_write_alignment = None
            store_bridge_alignment = None
            bridge_throttle_alignment = None

        elapsed_alignment = _delta_summary(
            [int(rtl_row["cycles"])],
            [int(core_summary["cycles"]) - core_origin],
        )
        exact_data_schedule = (
            request_alignment["max_abs_delta_cycles"] == 0
            and external_alignment["max_abs_delta_cycles"] == 0
            and child_alignment["max_abs_delta_cycles"] == 0
            and elapsed_alignment["max_abs_delta_cycles"] == 0
            and (
                child_write_alignment is None
                or child_write_alignment["max_abs_delta_cycles"] == 0
            )
            and (
                store_bridge_alignment is None
                or store_bridge_alignment["max_abs_delta_cycles"] == 0
            )
            and (
                bridge_throttle_alignment is None
                or bridge_throttle_alignment["max_abs_delta_cycles"] == 0
            )
            and (
                external_response_alignment is None
                or external_response_alignment["max_abs_delta_cycles"] == 0
            )
        )
        exact_address_schedule = burst_alignment["max_abs_delta_cycles"] == 0
        if not exact_data_schedule or not exact_address_schedule:
            raise RuntimeError(f"{case_id}: AXI transcript exceeded its bound")
        cases[case_id] = {
            "status": "EXACT",
            "core_origin_cycle": core_origin,
            "elapsed": elapsed_alignment,
            "requests": request_alignment,
            "burst_addresses_and_lengths_exact": True,
            "burst_issue": burst_alignment,
            "external_data": external_alignment,
            "external_response": external_response_alignment,
            "child_output": child_alignment,
            "child_write_ingress": child_write_alignment,
            "store_to_bridge": store_bridge_alignment,
            "bridge_to_throttle": bridge_throttle_alignment,
            "bridge_to_throttle_last_markers_exact":
                bridge_last_markers_exact,
            "max_outstanding": {
                "rtl": int(rtl_row["max_outstanding"]),
                "core": int(core_summary["max_outstanding"]),
            },
            "stall_ledger": {
                "rtl_address_valid_without_ready": int(
                    rtl_row["external_address_stalls"]
                ),
                "rtl_data_valid_without_ready": int(
                    rtl_row["external_data_stalls"]
                ),
                "rtl_child_output_valid_without_ready": int(
                    rtl_row["child_response_stalls"]
                ),
                "core_configured_address_withholding": int(
                    core_summary["address_stalls"]
                ),
                "core_configured_data_withholding": int(
                    core_summary["data_stalls"]
                ),
                "core_configured_response_withholding": int(
                    core_summary["response_stalls"]
                ),
                "core_child_output_withholding": int(
                    core_summary["child_stalls"]
                ),
                "semantics": (
                    "Diagnostic only: RTL counters observe VALID&&!READY; core "
                    "counters observe configured availability suppression and "
                    "registered FIFO occupancy, so totals are not equivalent."
                ),
            },
        }
    return {
        "status": "PASS_EXACT",
        "core_log": str(core_log),
        "core_log_sha256": sha256(core_log),
        "core_source_sha256": {
            str(path.relative_to(ROOT)): sha256(path) for path in CORE_SOURCES
        },
        "cases": cases,
        "claim": (
            "Deterministic child write ingress, internal write buffering, "
            "external AXI address/data/response, and child output events are "
            "exact after removing the core's one-cycle registered-input origin."
        ),
        "limitation": "Shared pseudochannel arbitration remains structural-only.",
    }


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
            "axi_write_buffer_pipeline_cycles": 0,
            "axi_serialize_write_bursts": True,
            "axi_write_ingress_fifo_depth": 16,
            "axi_write_throttle_fifo_depth": 16,
            "axi_write_ingress_pipeline_cycles": 8,
            "axi_write_address_after_full_burst_cycles": 2,
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
    oracle_dir: Path, before_dir: Path, after_dir: Path,
    core_log: Path = DEFAULT_CORE_LOG,
) -> dict[str, object]:
    hardware_holdout = compare_matrices(before_dir, after_dir)
    hardware_holdout["scope"] = (
        "Current 11-case Candidate10 maintenance matrix using the explicit "
        "read-output stage and structural write ingress. No residual fit is "
        "applied; hardware timings come from the frozen accepted xclbin."
    )
    return {
        "schema_version": 2,
        "claim": "candidate10_m_axi_adapter_execution_alignment",
        "rtl_oracle": summarize_oracle(oracle_dir),
        "backpressure_schedule": compare_backpressure_transcripts(
            oracle_dir, core_log
        ),
        "hardware_holdout": hardware_holdout,
        "claim_boundary": {
            "modeled": [
                "64-bit child word address to AXI byte address conversion",
                "16-beat and 4-KiB burst splitting",
                "read-address and write-buffer adapter pipelines",
                "deterministic AR/R/AW/W/B availability and FIFO backpressure",
                "16 outstanding bursts, 256-beat read reorder capacity",
                "ordered write-burst issue and finite FIFO backpressure",
                "Candidate10 16-entry store and throttle write FIFOs",
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
    parser.add_argument("--core-log", type=Path, default=DEFAULT_CORE_LOG)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    evidence = collect(
        args.oracle_dir.resolve(),
        args.before_dir.resolve(),
        args.after_dir.resolve(),
        args.core_log.resolve(),
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
