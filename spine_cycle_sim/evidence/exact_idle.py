"""Fail-closed equivalence checks for the exact-idle DRAMSim3 backend."""

from __future__ import annotations

import csv
import hashlib
import json
import math
from pathlib import Path
from typing import Any


SYSTEMS = ("spine", "grasu_regraph")
DIRECT_TRANSPORT_BACKEND_TRANSITION = (
    "sst_memHierarchy_dramsim3",
    "direct_dramsim3_transport",
)
FULL_PAGERANK_SPINE_ADDITIONS = frozenset(
    {
        "compute_max_memory_requests_inflight",
        "compute_memory_ledger_match",
        "compute_memory_request_fifo_stall_cycles",
        "compute_memory_requests_completed",
        "compute_memory_window_stall_cycles",
        "reader_cold_edges",
        "reader_construction_payload_bytes",
        "reader_construction_pipeline_requests",
        "reader_construction_pipeline_retires",
        "reader_edge_pipeline_axis_stall_cycles",
        "reader_edge_pipeline_credit_stall_cycles",
        "reader_edge_pipeline_max_buffered",
        "reader_edge_pipeline_max_inflight",
        "reader_edge_pipeline_request_fifo_stall_cycles",
        "reader_graph_bytes",
        "reader_graph_index_bitmap_misses",
        "reader_graph_index_bitmap_words",
        "reader_graph_index_payload_bytes",
        "reader_hot_edges",
        "reader_level_cache_bytes",
        "reader_max_active_memory_ports",
        "reader_max_memory_requests_inflight",
        "reader_max_memory_requests_inflight_per_port",
        "reader_memory_cross_port_overlap_cycles",
        "reader_memory_dependency_stall_cycles",
        "reader_memory_ledger_match",
        "reader_memory_request_fifo_stall_cycles",
        "reader_memory_requests_completed",
        "reader_memory_requests_issued",
        "reader_memory_window_stall_cycles",
        "reader_metadata_bytes",
        "reader_occupied_levels",
        "reader_range_active_records",
        "reader_range_construction_payloads",
        "reader_range_error",
        "reader_range_fallback_reason",
        "reader_range_family_probes",
        "reader_range_family_skips",
        "reader_range_level_checks",
        "reader_range_path",
        "reader_range_replay_payloads",
        "reader_range_row_lookups",
        "reader_range_tasks",
        "reader_replay_payload_bytes",
        "reader_replay_pipeline_requests",
        "reader_replay_pipeline_retires",
        "reader_row_lookup_metadata_bytes",
        "reader_tiles",
    }
)


class ExactIdleEquivalenceError(ValueError):
    """Raised when the exact-idle result changes an architectural observable."""


def _json(path: Path) -> dict[str, Any]:
    if not path.is_file():
        raise ExactIdleEquivalenceError(f"missing JSON: {path}")
    document = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(document, dict):
        raise ExactIdleEquivalenceError(f"expected JSON object: {path}")
    return document


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _require_same_bytes(baseline: Path, candidate: Path, label: str) -> None:
    if not baseline.is_file() or not candidate.is_file():
        raise ExactIdleEquivalenceError(f"missing {label}")
    if baseline.read_bytes() != candidate.read_bytes():
        raise ExactIdleEquivalenceError(f"{label} changed")


def _result_algorithms(
    root: Path, run_ids: list[str]
) -> dict[tuple[str, str], str]:
    path = root / "results.csv"
    if not path.is_file():
        raise ExactIdleEquivalenceError(f"missing result table: {path}")
    with path.open("r", encoding="utf-8", newline="") as stream:
        rows = list(csv.DictReader(stream))
    algorithms: dict[tuple[str, str], str] = {}
    for row in rows:
        key = (row.get("run_id", ""), row.get("system", ""))
        algorithm = row.get("algorithm", "")
        if (
            key in algorithms
            or key[0] not in run_ids
            or key[1] not in SYSTEMS
            or not algorithm
        ):
            raise ExactIdleEquivalenceError(f"invalid result identity row: {row}")
        algorithms[key] = algorithm
    expected = {(run_id, system) for run_id in run_ids for system in SYSTEMS}
    if set(algorithms) != expected:
        raise ExactIdleEquivalenceError(f"incomplete result table: {path}")
    return algorithms


def _validate_parent(
    root: Path,
) -> tuple[dict[str, Any], dict[tuple[str, str], str]]:
    manifest = _json(root / "comparison_manifest.json")
    run_ids = manifest.get("selected_run_ids")
    if (
        manifest.get("status") != "PASS"
        or manifest.get("failure") is not None
        or not isinstance(run_ids, list)
        or len(run_ids) != len(set(run_ids))
        or manifest.get("result_rows") != len(run_ids) * len(SYSTEMS)
        or manifest.get("paired_rows") != len(run_ids)
    ):
        raise ExactIdleEquivalenceError(f"incomplete comparison matrix: {root}")
    return manifest, _result_algorithms(root, run_ids)


def analyze_exact_idle_equivalence(
    baseline_dir: str | Path,
    candidate_dir: str | Path,
    *,
    allow_direct_transport: bool = False,
) -> dict[str, Any]:
    """Compare every architectural result field and every DRAM JSON byte."""

    baseline = Path(baseline_dir).resolve()
    candidate = Path(candidate_dir).resolve()
    baseline_manifest, baseline_algorithms = _validate_parent(baseline)
    candidate_manifest, candidate_algorithms = _validate_parent(candidate)
    baseline_runs = baseline_manifest["selected_run_ids"]
    if candidate_manifest["selected_run_ids"] != baseline_runs:
        raise ExactIdleEquivalenceError("run coverage or order changed")
    if candidate_algorithms != baseline_algorithms:
        raise ExactIdleEquivalenceError("result algorithm identity changed")

    rows: list[dict[str, Any]] = []
    total_dram_json = 0
    exact_result_files = 0
    old_fields = 0
    added_fields = 0
    speedups: list[float] = []
    approved_provenance_changes = 0
    for run_id in baseline_runs:
        for system in SYSTEMS:
            old_root = baseline / run_id / system
            new_root = candidate / run_id / system
            old_path = old_root / "result.json"
            new_path = new_root / "result.json"
            old = _json(old_path)
            new = _json(new_path)
            missing = set(old) - set(new)
            changed = {key for key in old.keys() & new.keys() if old[key] != new[key]}
            provenance_changes: set[str] = set()
            if "backend" in changed and allow_direct_transport:
                transition = (old.get("backend"), new.get("backend"))
                if transition != DIRECT_TRANSPORT_BACKEND_TRANSITION:
                    raise ExactIdleEquivalenceError(
                        f"{run_id}/{system} invalid backend transition: {transition}"
                    )
                changed.remove("backend")
                provenance_changes.add("backend")
            additions = set(new) - set(old)
            algorithm = baseline_algorithms[(run_id, system)]
            allowed = (
                FULL_PAGERANK_SPINE_ADDITIONS
                if system == "spine" and algorithm == "full_pagerank"
                else frozenset()
            )
            if missing or changed or additions != allowed:
                raise ExactIdleEquivalenceError(
                    f"{run_id}/{system} result mismatch: "
                    f"missing={sorted(missing)} changed={sorted(changed)} "
                    f"added={sorted(additions)} expected_added={sorted(allowed)}"
                )

            old_dram = {
                path.relative_to(old_root): path
                for path in (old_root / "dram").glob("channel*/*.json")
            }
            new_dram = {
                path.relative_to(new_root): path
                for path in (new_root / "dram").glob("channel*/*.json")
            }
            if not old_dram or set(old_dram) != set(new_dram):
                raise ExactIdleEquivalenceError(
                    f"{run_id}/{system} DRAM JSON coverage changed"
                )
            changed_dram = [
                str(relative)
                for relative in sorted(old_dram)
                if old_dram[relative].read_bytes() != new_dram[relative].read_bytes()
            ]
            if changed_dram:
                raise ExactIdleEquivalenceError(
                    f"{run_id}/{system} DRAM JSON changed: {changed_dram}"
                )

            old_run = _json(old_root / "shared_run.json")
            new_run = _json(new_root / "shared_run.json")
            old_wall = float(old_run["wall_seconds"])
            new_wall = float(new_run["wall_seconds"])
            if old_wall <= 0.0 or new_wall <= 0.0:
                raise ExactIdleEquivalenceError(
                    f"{run_id}/{system} has non-positive host runtime"
                )
            host_speedup = old_wall / new_wall
            speedups.append(host_speedup)
            byte_identical = old_path.read_bytes() == new_path.read_bytes()
            exact_result_files += int(byte_identical)
            old_fields += len(old)
            added_fields += len(additions)
            approved_provenance_changes += len(provenance_changes)
            total_dram_json += len(old_dram)
            rows.append(
                {
                    "run_id": run_id,
                    "system": system,
                    "algorithm": algorithm,
                    "cycles": old.get("cycles", 0),
                    "old_fields": len(old),
                    "added_observability_fields": len(additions),
                    "approved_provenance_changes": ",".join(
                        sorted(provenance_changes)
                    ),
                    "result_byte_identical": byte_identical,
                    "dram_json_files": len(old_dram),
                    "baseline_wall_seconds": old_wall,
                    "candidate_wall_seconds": new_wall,
                    "host_speedup": host_speedup,
                }
            )

    geomean = math.exp(sum(math.log(value) for value in speedups) / len(speedups))
    return {
        "schema_version": 1,
        "claim": (
            "direct_dramsim3_transport_architectural_equivalence"
            if allow_direct_transport
            else "exact_idle_backend_observable_equivalence"
        ),
        "baseline_manifest_sha256": _sha256(
            baseline / "comparison_manifest.json"
        ),
        "candidate_manifest_sha256": _sha256(
            candidate / "comparison_manifest.json"
        ),
        "run_cases": len(baseline_runs),
        "system_results": len(rows),
        "algorithms": sorted({str(row["algorithm"]) for row in rows}),
        "all_preexisting_result_fields_identical":
            approved_provenance_changes == 0,
        "all_architectural_result_fields_identical": True,
        "approved_provenance_changes": approved_provenance_changes,
        "preexisting_result_fields_compared": old_fields,
        "added_observability_fields": added_fields,
        "byte_identical_result_files": exact_result_files,
        "all_dram_json_byte_identical": True,
        "dram_json_files_compared": total_dram_json,
        "host_speedup_geomean": geomean,
        "rows": rows,
        "status": "PASS",
    }


def analyze_exact_idle_sensitivity_equivalence(
    baseline_dir: str | Path, candidate_dir: str | Path
) -> dict[str, Any]:
    """Validate every child of a shared-HBM sensitivity sweep."""

    baseline = Path(baseline_dir).resolve()
    candidate = Path(candidate_dir).resolve()
    baseline_manifest = _json(baseline / "sensitivity_manifest.json")
    candidate_manifest = _json(candidate / "sensitivity_manifest.json")
    stable_fields = (
        "schema_version",
        "matrix_id",
        "contract_sha256",
        "profiles",
        "run_ids",
        "pairs_per_profile",
        "strict_rank_inversions",
        "status",
    )
    changed_fields = [
        field
        for field in stable_fields
        if baseline_manifest.get(field) != candidate_manifest.get(field)
    ]
    profiles = baseline_manifest.get("profiles")
    run_ids = baseline_manifest.get("run_ids")
    if (
        changed_fields
        or baseline_manifest.get("schema_version") != 2
        or baseline_manifest.get("status") != "PASS"
        or baseline_manifest.get("strict_rank_inversions") != 0
        or not isinstance(profiles, list)
        or not profiles
        or len(profiles) != len(set(profiles))
        or not isinstance(run_ids, list)
        or not run_ids
        or len(run_ids) != len(set(run_ids))
        or baseline_manifest.get("pairs_per_profile") != len(run_ids)
    ):
        raise ExactIdleEquivalenceError(
            "invalid or changed sensitivity contract: "
            f"changed={changed_fields}"
        )

    for table in ("sensitivity_details.csv", "sensitivity_summary.csv"):
        _require_same_bytes(baseline / table, candidate / table, table)

    rows: list[dict[str, Any]] = []
    dram_json_files = 0
    old_fields = 0
    additions = 0
    exact_result_files = 0
    for profile_id in profiles:
        if not isinstance(profile_id, str) or not profile_id:
            raise ExactIdleEquivalenceError("invalid sensitivity profile ID")
        report = analyze_exact_idle_equivalence(
            baseline / profile_id, candidate / profile_id
        )
        if report["run_cases"] != len(run_ids):
            raise ExactIdleEquivalenceError(
                f"{profile_id}: child run coverage differs from parent"
            )
        for row in report.pop("rows"):
            rows.append({"profile_id": profile_id, **row})
        dram_json_files += int(report["dram_json_files_compared"])
        old_fields += int(report["preexisting_result_fields_compared"])
        additions += int(report["added_observability_fields"])
        exact_result_files += int(report["byte_identical_result_files"])

    speedups = [float(row["host_speedup"]) for row in rows]
    host_geomean = math.exp(
        sum(math.log(value) for value in speedups) / len(speedups)
    )
    return {
        "schema_version": 1,
        "claim": "exact_idle_hbm_sensitivity_observable_equivalence",
        "baseline_sensitivity_manifest_sha256": _sha256(
            baseline / "sensitivity_manifest.json"
        ),
        "candidate_sensitivity_manifest_sha256": _sha256(
            candidate / "sensitivity_manifest.json"
        ),
        "profiles": profiles,
        "run_cases_per_profile": len(run_ids),
        "system_results": len(rows),
        "all_preexisting_result_fields_identical": True,
        "preexisting_result_fields_compared": old_fields,
        "added_observability_fields": additions,
        "byte_identical_result_files": exact_result_files,
        "all_dram_json_byte_identical": True,
        "dram_json_files_compared": dram_json_files,
        "derived_sensitivity_tables_byte_identical": True,
        "strict_rank_inversions": 0,
        "host_speedup_geomean": host_geomean,
        "rows": rows,
        "status": "PASS",
    }
