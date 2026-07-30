"""Correctness-gated analysis of formal publication campaign results."""

from __future__ import annotations

import csv
import hashlib
import json
import math
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence


PUBLICATION_RESULT_SYSTEMS = (
    "spine",
    "grasu_regraph_k1",
    "grasu_regraph_k4_shared",
)
FLOAT_FINAL_STATE_TOLERANCE = 1.0e-5


def _stable_digest(value: object) -> str:
    encoded = json.dumps(
        value, sort_keys=True, separators=(",", ":")
    ).encode("ascii")
    return hashlib.sha256(encoded).hexdigest()


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(4 * 1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _case_group_identity(case: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "dataset_id": case["dataset_id"],
        "algorithm": case["algorithm"],
        "scenario": case["scenario"],
        "batch_size": case["batch_size"],
        "graph_sha256": case["graph"]["sha256"],
        "update_sha256": case["update"]["sha256"],
        "source": case["source"],
        "algorithm_parameters": case["algorithm_parameters"],
    }


def _scientific_signature(result: Mapping[str, Any]) -> str:
    row = result["row"]
    scalar_metrics = {
        key: value
        for key, value in result.get("scalar_metrics", {}).items()
        if not str(key).endswith("wall_seconds")
    }
    return _stable_digest(
        {
            "case": result["case"],
            "cycles": row["cycles"],
            "final_state": result["final_state"],
            "scalar_metrics": scalar_metrics,
            "backend_arbitration": result.get("backend_arbitration"),
            "backend_traffic": result.get("backend_traffic"),
            "dram": result.get("dram"),
            "plugin_sha256": result["plugin_sha256"],
        }
    )


def _validate_result_supersedence_policy(
    policy: Mapping[str, Any] | None,
) -> None:
    if policy is None:
        return
    old_hashes = policy.get("superseded_plugin_sha256")
    if (
        policy.get("classification") != "hls_behavior_correction"
        or policy.get("scope_system") != "spine"
        or policy.get("affected_metric") != "resident_hot_edges"
        or policy.get("affected_when_greater_than") != 0
        or policy.get("requires_identical_case") is not True
        or policy.get("requires_identical_final_state") is not True
        or not isinstance(old_hashes, list)
        or not old_hashes
        or len(set(old_hashes)) != len(old_hashes)
        or not isinstance(policy.get("superseding_plugin_sha256"), str)
        or policy["superseding_plugin_sha256"] in old_hashes
    ):
        raise ValueError("invalid result supersedence policy")


def _transition_classification(
    result: Mapping[str, Any], policy: Mapping[str, Any] | None
) -> str:
    if policy is None or result["case"]["system"] != policy["scope_system"]:
        return "eligible"
    plugin = result["plugin_sha256"]
    if plugin == policy["superseding_plugin_sha256"]:
        return "successor"
    if plugin not in policy["superseded_plugin_sha256"]:
        return "eligible"
    metric = policy["affected_metric"]
    value = result.get("scalar_metrics", {}).get(metric)
    if not isinstance(value, (int, float)) or isinstance(value, bool):
        raise ValueError(
            f"superseded Spine result lacks numeric transition metric: {metric}"
        )
    return (
        "invalidated"
        if value > policy["affected_when_greater_than"]
        else "eligible"
    )


def _validate_case_result(result: Mapping[str, Any]) -> None:
    if result.get("schema_version") != 1 or result.get("status") != "pass":
        raise ValueError("publication case result is not passing schema v1")
    case = result.get("case")
    row = result.get("row")
    final = result.get("final_state")
    if not all(isinstance(value, Mapping) for value in (case, row, final)):
        raise ValueError("publication case result lacks case, row, or final state")
    if case.get("system") not in PUBLICATION_RESULT_SYSTEMS:
        raise ValueError(f"unknown publication result system: {case.get('system')}")
    row_system = row.get("system")
    compatible_internal_alias = (
        str(case.get("system", "")).startswith("grasu_regraph_")
        and row_system == "grasu_regraph"
    )
    if row_system != case.get("system") and not compatible_internal_alias:
        raise ValueError("publication case and row systems differ")
    if row.get("run_id") != case.get("execution_id"):
        raise ValueError("publication case and row execution IDs differ")
    if int(row.get("cycles", 0)) <= 0:
        raise ValueError("publication result cycles must be positive")
    if int(final.get("count", -1)) != int(case["graph"]["vertices"]):
        raise ValueError("publication final-state vector is incomplete")
    for key in (
        "architecture_correctness_mismatches",
        "mathematical_correctness_mismatches",
    ):
        if int(row.get(key, -1)) != 0:
            raise ValueError(f"publication result failed {key}")
    plugin_hash = result.get("plugin_sha256")
    if not (
        isinstance(plugin_hash, str)
        and len(plugin_hash) == 64
        and all(character in "0123456789abcdef" for character in plugin_hash)
    ):
        raise ValueError("publication result lacks a valid plugin hash")
    admission = result.get("admission", {})
    if admission.get("child_returncode") != 0:
        raise ValueError("publication child process did not pass")
    parent_checks = admission.get("parent_checks")
    if isinstance(parent_checks, Mapping) and not all(parent_checks.values()):
        raise ValueError("publication parent checks did not all pass")
    parent_problems = admission.get("parent_problems")
    if isinstance(parent_problems, list) and parent_problems:
        raise ValueError("publication parent admission has problems")
    arbitration = result.get("backend_arbitration")
    if isinstance(arbitration, Mapping) and arbitration.get("ledger_closed") is not True:
        raise ValueError("publication backend arbitration ledger is open")


def _metric(row: Mapping[str, Any], *keys: str, default: Any = 0) -> Any:
    for key in keys:
        if key in row and row[key] is not None:
            return row[key]
    return default


def _measurement_window_cycles(result: Mapping[str, Any]) -> int:
    case = result["case"]
    raw = result["row"]
    scalar = result.get("scalar_metrics", {})
    if (
        case["system"] == "spine"
        and case["algorithm"] == "weighted_sssp"
        and int(_metric(scalar, "update_cycles", default=0)) > 0
    ):
        return int(scalar["update_cycles"])
    return int(raw["cycles"])


def _normalized_system_row(result: Mapping[str, Any]) -> dict[str, Any]:
    case = result["case"]
    raw = result["row"]
    scalar = result.get("scalar_metrics", {})
    traffic = result.get("backend_traffic") or {}
    combined = traffic.get("combined", {}) if isinstance(traffic, Mapping) else {}
    reads = traffic.get("reads", {}) if isinstance(traffic, Mapping) else {}
    writes = traffic.get("writes", {}) if isinstance(traffic, Mapping) else {}
    cycles = _measurement_window_cycles(result)
    clock_mhz = float(_metric(raw, "clock_mhz", "core_mhz"))
    update_cycles = int(
        _metric(scalar, "update_cycles", "maintenance_cycles", default=0)
    )
    logical_mutations = int(case["update"]["user_mutations"])
    requests = int(_metric(combined, "requests", default=raw.get("backend_requests", 0)))
    contiguous = int(_metric(combined, "contiguous_requests", default=0))
    discontinuous = int(_metric(combined, "discontinuous_requests", default=0))
    classified = contiguous + discontinuous
    return {
        "execution_id": case["execution_id"],
        "logical_views": "+".join(sorted(set(result.get("logical_views", [])))),
        "group_id": _stable_digest(_case_group_identity(case))[:20],
        "dataset_id": case["dataset_id"],
        "dataset_kind": raw["dataset_kind"],
        "role": raw["role"],
        "algorithm": case["algorithm"],
        "scenario": case["scenario"],
        "batch_size": int(case["batch_size"]),
        "system": case["system"],
        "vertices": int(case["graph"]["vertices"]),
        "initial_edges": int(case["graph"]["records"]),
        "logical_user_mutations": logical_mutations,
        "physical_update_records": int(case["update"]["physical_records"]),
        "cycles": cycles,
        "raw_cycles": int(raw.get("raw_cycles", raw["cycles"])),
        "bootstrap_cycles": int(
            raw.get("bootstrap_cycles", _metric(scalar, "cold_cycles", default=0))
        ),
        "measurement_window": raw.get(
            "measurement_window",
            "dynamic_update_only"
            if case["system"] == "spine" and case["algorithm"] == "weighted_sssp"
            else "complete_execution",
        ),
        "algorithm_warm_start": bool(
            raw.get(
                "algorithm_warm_start",
                _metric(scalar, "algorithm_warm_start", default=False),
            )
        ),
        "clock_mhz": clock_mhz,
        "simulated_us": cycles / clock_mhz,
        "update_cycles": update_cycles,
        "update_mups": (
            logical_mutations * clock_mhz / update_cycles
            if update_cycles > 0
            else 0.0
        ),
        "e2e_mups": logical_mutations * clock_mhz / cycles,
        "backend_requests": requests,
        "read_bytes": int(_metric(reads, "bytes", default=raw.get("read_bytes", 0))),
        "write_bytes": int(_metric(writes, "bytes", default=raw.get("write_bytes", 0))),
        "contiguous_requests": contiguous,
        "discontinuous_requests": discontinuous,
        "sequential_request_fraction": contiguous / classified if classified else 0.0,
        "random_request_fraction": discontinuous / classified if classified else 0.0,
        "hbm_queue_stalls": int(
            _metric(raw, "hbm_queue_stalls", "backend_arbitration_request_waits")
        ),
        "dram_energy_pj": float(
            _metric(raw, "dram_energy_pj", "dram_total_energy_pj", default=0.0)
        ),
        "host_wall_seconds": float(
            _metric(raw, "host_wall_seconds", "wall_seconds", default=0.0)
        ),
        "final_state_sha256": result["final_state"]["sha256"],
        "plugin_sha256": result["plugin_sha256"],
    }


def _activity_value(value: Any) -> int:
    if isinstance(value, bool) or value is None:
        return 0
    if isinstance(value, (int, float)):
        if not math.isfinite(float(value)) or value < 0:
            raise ValueError("publication activity counter must be nonnegative")
        return int(value)
    if isinstance(value, (list, tuple)):
        return sum(_activity_value(item) for item in value)
    if isinstance(value, Mapping):
        return sum(_activity_value(item) for item in value.values())
    return 0


def _activity_sum(metrics: Mapping[str, Any], keys: Sequence[str]) -> int:
    return sum(_activity_value(metrics.get(key)) for key in keys)


def _activity_first(metrics: Mapping[str, Any], keys: Sequence[str]) -> int:
    for key in keys:
        if key in metrics and metrics[key] is not None:
            return _activity_value(metrics[key])
    return 0


def _activity_alias_group_sum(
    metrics: Mapping[str, Any], groups: Sequence[Sequence[str]]
) -> int:
    return sum(_activity_first(metrics, group) for group in groups)


def _component_activity_rows(result: Mapping[str, Any]) -> list[dict[str, Any]]:
    """Normalize architecture counters without claiming a total-energy model."""

    case = result["case"]
    metrics = result.get("scalar_metrics", {})
    if not isinstance(metrics, Mapping):
        raise ValueError("publication scalar_metrics must be an object")
    total_cycles = _measurement_window_cycles(result)
    group_id = _stable_digest(_case_group_identity(case))[:20]
    system = str(case["system"])
    common = {
        "execution_id": case["execution_id"],
        "group_id": group_id,
        "dataset_id": case["dataset_id"],
        "algorithm": case["algorithm"],
        "scenario": case["scenario"],
        "batch_size": int(case["batch_size"]),
        "system": system,
        "plugin_sha256": result["plugin_sha256"],
        "claim_scope": "workload_specific_activity_not_total_energy",
    }
    rows: list[dict[str, Any]] = []

    def add(
        component: str,
        *,
        cycles: int = 0,
        work_items: int = 0,
        read_events: int = 0,
        write_events: int = 0,
        backend_requests: int = 0,
        stall_cycles: int = 0,
        counter_contract: str,
    ) -> None:
        rows.append(
            {
                **common,
                "component": component,
                "component_cycles": cycles,
                "work_items": work_items,
                "read_events": read_events,
                "write_events": write_events,
                "backend_requests": backend_requests,
                "stall_cycles": stall_cycles,
                "counter_contract": counter_contract,
            }
        )

    if system == "spine":
        maintenance_cycles = _activity_first(
            metrics, ("maintenance_cycles", "update_cycles")
        )
        add(
            "maintenance",
            cycles=maintenance_cycles,
            work_items=_activity_first(
                metrics, ("maintenance_edge_visits", "update_edges")
            ),
            backend_requests=_activity_first(
                metrics, ("maintenance_backend_requests", "update_backend_requests")
            ),
            stall_cycles=_activity_sum(
                metrics,
                (
                    "maintenance_memory_dependency_stall_cycles",
                    "maintenance_memory_request_fifo_stall_cycles",
                    "maintenance_memory_window_stall_cycles",
                    "maintenance_scan_ii_stall_cycles",
                    "maintenance_scan_reorder_full_stall_cycles",
                    "maintenance_scan_response_stall_cycles",
                    "maintenance_l0_writer_backpressure_stall_cycles",
                ),
            ),
            counter_contract="spine_maintenance_execution_and_memory_v1",
        )
        reader_cycles = _activity_first(
            metrics, ("reader_cycles", "reader_active_cycles_per_round")
        )
        reader_requests = _activity_first(
            metrics,
            ("reader_memory_requests_issued", "reader_memory_requests_issued_per_round"),
        )
        add(
            "reader",
            cycles=reader_cycles,
            work_items=_activity_first(
                metrics,
                ("reader_edges_total", "reader_edges", "edge_axis_transfers_per_round"),
            ),
            backend_requests=reader_requests,
            stall_cycles=_activity_alias_group_sum(
                metrics,
                (
                    (
                        "reader_memory_dependency_stall_cycles",
                        "reader_memory_dependency_stall_cycles_per_round",
                    ),
                    (
                        "reader_memory_request_fifo_stall_cycles",
                        "reader_memory_request_fifo_stall_cycles_per_round",
                    ),
                    (
                        "reader_memory_window_stall_cycles",
                        "reader_memory_window_stall_cycles_per_round",
                    ),
                    (
                        "reader_edge_pipeline_axis_stall_cycles",
                        "reader_edge_pipeline_axis_stall_cycles_per_round",
                    ),
                    (
                        "reader_edge_pipeline_credit_stall_cycles",
                        "reader_edge_pipeline_credit_stall_cycles_per_round",
                    ),
                ),
            ),
            counter_contract="spine_reader_execution_and_memory_v1",
        )
        compute_cycles = _activity_first(
            metrics, ("compute_cycles", "compute_active_cycles_per_round")
        )
        if compute_cycles == 0:
            compute_cycles = max(0, total_cycles - maintenance_cycles - reader_cycles)
        add(
            "compute",
            cycles=compute_cycles,
            work_items=_activity_first(
                metrics,
                (
                    "compute_edges_total",
                    "compute_edges",
                    "edge_axis_transfers",
                    "edge_axis_transfers_per_round",
                    "apply_operations",
                ),
            ),
            backend_requests=_activity_first(
                metrics,
                ("compute_backend_requests", "compute_memory_requests_issued_per_round"),
            ),
            stall_cycles=_activity_alias_group_sum(
                metrics,
                (
                    (
                        "compute_memory_request_fifo_stall_cycles",
                        "compute_memory_request_fifo_stall_cycles_per_round",
                    ),
                    (
                        "compute_memory_window_stall_cycles",
                        "compute_memory_window_stall_cycles_per_round",
                    ),
                    ("compute_on_chip_pipeline_stall_cycles_per_round",),
                ),
            ),
            counter_contract="spine_compute_execution_and_memory_v1",
        )
        add(
            "onchip_state_arrays",
            cycles=_activity_first(
                metrics, ("compute_on_chip_controller_cycles_per_round",)
            ),
            read_events=_activity_sum(
                metrics,
                (
                    "compute_tiny_bram_read_requests_per_round",
                    "compute_vs_uram_read_requests_per_round",
                    "compute_active_emit_lane_reads_per_round",
                    "compute_sparse_store_lane_reads_per_round",
                ),
            ),
            write_events=_activity_sum(
                metrics,
                (
                    "compute_tiny_bram_write_requests_per_round",
                    "compute_vs_uram_write_requests_per_round",
                    "compute_active_emit_lane_writes_per_round",
                    "compute_tile_active_clear_lane_writes_per_round",
                    "compute_tile_active_mark_writes_per_round",
                ),
            ),
            counter_contract="spine_selected_bram_uram_bitmap_accesses_v1",
        )
        add(
            "axis_streams",
            work_items=(
                _activity_first(metrics, ("edge_axis_transfers", "edge_axis_transfers_per_round"))
                + _activity_first(
                    metrics, ("value_axis_transfers", "value_axis_transfers_per_round")
                )
            ),
            stall_cycles=_activity_first(
                metrics,
                (
                    "axis_push_stalls",
                    "edge_axis_push_stalls",
                    "edge_axis_push_stalls_per_round",
                ),
            ),
            counter_contract="spine_axis_transfer_backpressure_v1",
        )
    else:
        add(
            "update_pma",
            cycles=_activity_first(metrics, ("update_cycles",)),
            work_items=_activity_first(metrics, ("update_edges", "logical_updates")),
            read_events=_activity_sum(
                metrics, ("update_pma_reads", "update_row_reads", "degree_update_reads")
            ),
            write_events=_activity_sum(
                metrics, ("update_pma_writes", "degree_update_writes")
            ),
            backend_requests=_activity_first(metrics, ("update_backend_requests",)),
            counter_contract="grasu_update_pma_execution_v1",
        )
        add(
            "source_cache",
            cycles=_activity_sum(metrics, ("source_prepare_cycles", "source_map_cycles")),
            work_items=_activity_first(metrics, ("source_cache_requests",)),
            read_events=_activity_first(metrics, ("compute_pma_slots",)),
            write_events=_activity_first(metrics, ("source_cache_lane_writes",)),
            stall_cycles=_activity_sum(
                metrics, ("source_cache_wait_cycles", "source_cache_output_stall_cycles")
            ),
            counter_contract="grasu_regraph_source_cache_accesses_v1",
        )
        gather_updates = _activity_first(metrics, ("gather_bank_updates",))
        gather_merge = _activity_first(metrics, ("gather_merge_cycles",))
        gather_reset = _activity_first(metrics, ("gather_reset_cycles",))
        gather_banks = _activity_first(metrics, ("gather_banks",)) or 8
        add(
            "gather",
            cycles=gather_merge + gather_reset,
            work_items=gather_updates,
            read_events=gather_updates + gather_merge * gather_banks,
            write_events=(
                gather_updates + (gather_merge + gather_reset) * gather_banks
            ),
            stall_cycles=_activity_sum(
                metrics, ("gather_bank_conflict_cycles", "gather_output_stall_cycles")
            ),
            counter_contract="regraph_gather_bank_accesses_v1",
        )
        add(
            "merger",
            work_items=_activity_first(metrics, ("merger_rows_consumed",)),
            write_events=_activity_first(metrics, ("merger_bursts_emitted",)),
            stall_cycles=_activity_first(metrics, ("merger_output_stall_cycles",)),
            counter_contract="regraph_merger_stream_activity_v1",
        )
        add(
            "apply",
            work_items=_activity_first(
                metrics, ("apply_input_bursts", "apply_operations")
            ),
            read_events=_activity_first(metrics, ("apply_state_reads",)),
            write_events=_activity_first(metrics, ("apply_state_writes",)),
            stall_cycles=_activity_sum(
                metrics,
                (
                    "apply_output_stall_cycles",
                    "apply_pipeline_capacity_stalls",
                    "apply_read_window_stalls",
                    "apply_write_window_stalls",
                ),
            ),
            counter_contract="regraph_apply_pipeline_activity_v1",
        )
        update_cycles = _activity_first(metrics, ("update_cycles",))
        add(
            "compute_pipeline_aggregate",
            cycles=_activity_first(metrics, ("compute_cycles",))
            or max(0, total_cycles - update_cycles),
            work_items=_activity_first(
                metrics,
                ("compute_active_edges", "compute_edges", "active_edges", "apply_operations"),
            ),
            backend_requests=_activity_first(metrics, ("compute_backend_requests",)),
            stall_cycles=_activity_first(metrics, ("axis_push_stalls",)),
            counter_contract="grasu_regraph_compute_aggregate_v1",
        )

    traffic = result.get("dram", {})
    if not isinstance(traffic, Mapping):
        traffic = {}
    add(
        "hbm_frontend",
        cycles=total_cycles,
        read_events=_activity_first(traffic, ("reads",)),
        write_events=_activity_first(traffic, ("writes",)),
        backend_requests=_activity_first(metrics, ("backend_requests",)),
        stall_cycles=_activity_sum(
            metrics,
            (
                "hbm_queue_stalls",
                "hbm_response_queue_stalls",
                "axi_issue_stalls",
            ),
        ),
        counter_contract="shared_axi_hbm_request_and_stall_v1",
    )
    return rows


def _external_final_vector(result: Mapping[str, Any]) -> list[int | float]:
    path = Path(str(result.get("raw_result_path", "")))
    expected_hash = result.get("raw_result_sha256")
    if not path.is_file() or not isinstance(expected_hash, str):
        raise ValueError("publication result lacks its hashed raw result")
    if _sha256_file(path) != expected_hash:
        raise ValueError(f"publication raw result changed: {path}")
    payload = json.loads(path.read_text(encoding="utf-8"))
    algorithm = str(result["case"]["algorithm"])
    if algorithm == "weighted_sssp":
        keys = ("distances_external", "final_values")
    elif algorithm == "connected_components":
        keys = ("labels_external", "labels")
    else:
        keys = ("ranks_external", "ranks", "final_values")
    raw_values = next(
        (payload[key] for key in keys if isinstance(payload.get(key), list)),
        None,
    )
    if raw_values is None:
        raise ValueError(f"publication raw result lacks external {algorithm} state")
    if len(raw_values) != int(result["case"]["graph"]["vertices"]):
        raise ValueError("publication raw external vector is incomplete")
    if algorithm == "weighted_sssp":
        return [
            0xFFFFFFFF if int(value) >= 0x7FFFFFFE else int(value)
            for value in raw_values
        ]
    if algorithm == "connected_components":
        return [int(value) for value in raw_values]
    return [float(value) for value in raw_values]


def _cross_system_final_state(
    results: Sequence[Mapping[str, Any]],
) -> dict[str, Any]:
    hashes = {str(result["final_state"]["sha256"]) for result in results}
    if len(hashes) == 1:
        return {
            "passed": True,
            "method": "canonical_exact_sha256",
            "exact_match": True,
            "max_abs_error": 0.0,
            "l1_error": 0.0,
            "tolerance": 0.0,
        }
    algorithm = str(results[0]["case"]["algorithm"])
    vectors = [_external_final_vector(result) for result in results]
    reference = vectors[0]
    if algorithm in {"weighted_sssp", "connected_components"}:
        exact = all(vector == reference for vector in vectors[1:])
        return {
            "passed": exact,
            "method": "canonical_external_integer_vector",
            "exact_match": exact,
            "max_abs_error": 0.0 if exact else math.inf,
            "l1_error": 0.0 if exact else math.inf,
            "tolerance": 0.0,
        }
    # The PageRank runners and their independent float64 oracles use this
    # tolerance for float32 reduction-order differences. This is distinct from
    # Residual PageRank's per-vertex 1e-6 activation threshold.
    tolerance = FLOAT_FINAL_STATE_TOLERANCE
    max_abs = 0.0
    l1_error = 0.0
    exact = True
    for vector in vectors[1:]:
        for expected, actual in zip(reference, vector, strict=True):
            difference = abs(float(expected) - float(actual))
            max_abs = max(max_abs, difference)
            l1_error += difference
            exact &= difference == 0.0
    return {
        "passed": math.isfinite(max_abs) and max_abs <= tolerance,
        "method": "canonical_external_float_vector_tolerance",
        "exact_match": exact,
        "max_abs_error": max_abs,
        "l1_error": l1_error,
        "tolerance": tolerance,
    }


def analyze_publication_case_results(
    results: Sequence[Mapping[str, Any]],
    *,
    expected_execution_ids: Iterable[str] = (),
    expected_execution_records: Mapping[str, Mapping[str, Any]] | None = None,
    capacity_exclusion_records: Sequence[Mapping[str, Any]] = (),
    result_supersedence_policy: Mapping[str, Any] | None = None,
    require_complete: bool = False,
) -> dict[str, Any]:
    """Validate, de-duplicate, pair, and summarize formal case results."""

    _validate_result_supersedence_policy(result_supersedence_policy)
    grouped_results: dict[str, list[Mapping[str, Any]]] = {}
    for result in results:
        _validate_case_result(result)
        grouped_results.setdefault(str(result["case"]["execution_id"]), []).append(
            result
        )

    by_execution: dict[str, Mapping[str, Any]] = {}
    duplicate_counts: dict[str, int] = {}
    invalidated_results: dict[str, list[Mapping[str, Any]]] = {}
    superseded_result_rows: list[dict[str, Any]] = []
    for execution_id, candidates in grouped_results.items():
        duplicate_counts[execution_id] = len(candidates)
        eligible: list[Mapping[str, Any]] = []
        invalidated: list[Mapping[str, Any]] = []
        successors: list[Mapping[str, Any]] = []
        for result in candidates:
            classification = _transition_classification(
                result, result_supersedence_policy
            )
            if classification == "invalidated":
                invalidated.append(result)
            else:
                eligible.append(result)
                if classification == "successor":
                    successors.append(result)
        invalidated_results[execution_id] = invalidated

        signatures = {_scientific_signature(result) for result in eligible}
        if len(signatures) > 1:
            raise ValueError(
                f"duplicate publication execution changed scientific result: {execution_id}"
            )
        if not eligible:
            continue
        selected = eligible[0]
        if invalidated:
            if not successors:
                raise ValueError(
                    "transition-invalidated result coexists with a non-successor: "
                    f"{execution_id}"
                )
            selected = successors[0]
            for old in invalidated:
                if old["case"] != selected["case"]:
                    raise ValueError(
                        f"superseding result changed case identity: {execution_id}"
                    )
                if old["final_state"] != selected["final_state"]:
                    raise ValueError(
                        f"superseding result changed final state: {execution_id}"
                    )
                assert result_supersedence_policy is not None
                metric = result_supersedence_policy["affected_metric"]
                superseded_result_rows.append(
                    {
                        "execution_id": execution_id,
                        "system": selected["case"]["system"],
                        "affected_metric": metric,
                        "affected_metric_value": old["scalar_metrics"][metric],
                        "old_plugin_sha256": old["plugin_sha256"],
                        "new_plugin_sha256": selected["plugin_sha256"],
                        "old_cycles": old["row"]["cycles"],
                        "new_cycles": selected["row"]["cycles"],
                        "case_identity_match": True,
                        "final_state_match": True,
                    }
                )
        by_execution[execution_id] = selected
    superseded_result_rows.sort(
        key=lambda row: (str(row["execution_id"]), str(row["old_plugin_sha256"]))
    )

    system_rows = [_normalized_system_row(result) for result in by_execution.values()]
    activity_rows = [
        row
        for result in by_execution.values()
        for row in _component_activity_rows(result)
    ]
    activity_rows.sort(
        key=lambda row: (
            row["dataset_id"],
            row["algorithm"],
            row["scenario"],
            row["batch_size"],
            row["system"],
            row["component"],
        )
    )
    system_rows.sort(
        key=lambda row: (
            row["dataset_id"],
            row["algorithm"],
            row["scenario"],
            row["batch_size"],
            row["system"],
        )
    )
    groups: dict[str, dict[str, dict[str, Any]]] = {}
    for row in system_rows:
        groups.setdefault(row["group_id"], {})[row["system"]] = row

    correctness_groups: list[dict[str, Any]] = []
    pair_rows: list[dict[str, Any]] = []
    for group_id, systems in sorted(groups.items()):
        sample = next(iter(systems.values()))
        missing_systems = sorted(set(PUBLICATION_RESULT_SYSTEMS) - set(systems))
        group_results = [
            by_execution[row["execution_id"]] for row in systems.values()
        ]
        equivalence = _cross_system_final_state(group_results)
        correctness_groups.append(
            {
                "group_id": group_id,
                "dataset_id": sample["dataset_id"],
                "algorithm": sample["algorithm"],
                "scenario": sample["scenario"],
                "batch_size": sample["batch_size"],
                "systems_present": "+".join(sorted(systems)),
                "missing_systems": "+".join(missing_systems),
                "complete_triplet": not missing_systems,
                "final_state_match": equivalence["passed"],
                "final_state_method": equivalence["method"],
                "final_state_exact_match": equivalence["exact_match"],
                "cross_system_max_abs_error": equivalence["max_abs_error"],
                "cross_system_l1_error": equivalence["l1_error"],
                "cross_system_tolerance": equivalence["tolerance"],
            }
        )
        if not equivalence["passed"]:
            continue
        spine = systems.get("spine")
        if spine is None:
            continue
        for competitor in ("grasu_regraph_k1", "grasu_regraph_k4_shared"):
            other = systems.get(competitor)
            if other is None:
                continue
            pair_rows.append(
                {
                    "group_id": group_id,
                    "dataset_id": sample["dataset_id"],
                    "dataset_kind": sample["dataset_kind"],
                    "algorithm": sample["algorithm"],
                    "scenario": sample["scenario"],
                    "batch_size": sample["batch_size"],
                    "competitor": competitor,
                    "spine_cycles": spine["cycles"],
                    "competitor_cycles": other["cycles"],
                    "spine_speedup": other["cycles"] / spine["cycles"],
                    "spine_update_cycles": spine["update_cycles"],
                    "competitor_update_cycles": other["update_cycles"],
                    "spine_update_speedup": (
                        other["update_cycles"] / spine["update_cycles"]
                        if spine["update_cycles"] > 0
                        and other["update_cycles"] > 0
                        else 0.0
                    ),
                    "spine_memory_bytes": spine["read_bytes"] + spine["write_bytes"],
                    "competitor_memory_bytes": other["read_bytes"] + other["write_bytes"],
                    "spine_random_request_fraction": spine["random_request_fraction"],
                    "competitor_random_request_fraction": other["random_request_fraction"],
                    "spine_dram_energy_pj": spine["dram_energy_pj"],
                    "competitor_dram_energy_pj": other["dram_energy_pj"],
                    "spine_energy_advantage": (
                        other["dram_energy_pj"] / spine["dram_energy_pj"]
                        if spine["dram_energy_pj"] > 0
                        else 0.0
                    ),
                }
            )

    expected_records = expected_execution_records or {}
    expected = set(expected_execution_ids)
    if expected_records:
        record_ids = set(expected_records)
        if expected and expected != record_ids:
            raise ValueError("expected execution IDs and records differ")
        expected = record_ids
    observed = set(by_execution)
    missing = sorted(expected - observed)
    unexpected = sorted(observed - expected) if expected else []
    execution_coverage_rows: list[dict[str, Any]] = []
    coverage_ids = expected | observed
    for execution_id in sorted(coverage_ids):
        metadata = expected_records.get(execution_id, {})
        result = by_execution.get(execution_id)
        was_invalidated = (
            bool(invalidated_results.get(execution_id)) and result is None
        )
        case = result["case"] if result is not None else {}
        normalized = (
            _normalized_system_row(result) if result is not None else {}
        )
        is_expected = execution_id in expected if expected else True
        is_observed = result is not None
        execution_coverage_rows.append(
            {
                "execution_id": execution_id,
                "dataset_id": metadata.get("dataset_id", case.get("dataset_id", "")),
                "algorithm": metadata.get("algorithm", case.get("algorithm", "")),
                "scenario": metadata.get("scenario", case.get("scenario", "")),
                "batch_size": metadata.get("batch_size", case.get("batch_size", "")),
                "system": metadata.get("system", case.get("system", "")),
                "tier": metadata.get("tier", ""),
                "logical_views": metadata.get(
                    "logical_views", normalized.get("logical_views", "")
                ),
                "campaign_ids": metadata.get("campaign_ids", ""),
                "estimated_rss_gib": metadata.get("estimated_rss_gib", ""),
                "expected": is_expected,
                "observed": is_observed,
                "coverage_status": (
                    "observed_pass"
                    if is_expected and is_observed
                    else (
                        (
                            "invalidated_by_behavior_transition"
                            if was_invalidated
                            else "missing"
                        )
                        if is_expected
                        else "unexpected_observed_pass"
                    )
                ),
                "cycles": normalized.get("cycles", ""),
                "host_wall_seconds": normalized.get("host_wall_seconds", ""),
            }
        )
    for exclusion in capacity_exclusion_records:
        execution_id = str(exclusion.get("execution_id", ""))
        if not execution_id:
            raise ValueError("capacity exclusion lacks execution ID")
        if execution_id in coverage_ids:
            raise ValueError(
                f"capacity-excluded execution is runnable or observed: {execution_id}"
            )
        execution_coverage_rows.append(
            {
                "execution_id": execution_id,
                "dataset_id": exclusion.get("dataset_id", ""),
                "algorithm": exclusion.get("algorithm", ""),
                "scenario": exclusion.get("scenario", ""),
                "batch_size": exclusion.get("batch_size", ""),
                "system": exclusion.get("system", ""),
                "tier": exclusion.get("tier", ""),
                "logical_views": exclusion.get("tier", ""),
                "campaign_ids": exclusion.get("campaign_ids", ""),
                "estimated_rss_gib": "",
                "expected": False,
                "observed": False,
                "coverage_status": "capacity_excluded",
                "cycles": "",
                "host_wall_seconds": "",
            }
        )
    execution_coverage_rows.sort(key=lambda row: str(row["execution_id"]))
    incomplete_groups = sum(
        not row["complete_triplet"] for row in correctness_groups
    )
    failed_correctness_groups = sum(
        not row["final_state_match"] for row in correctness_groups
    )
    complete = (
        not missing
        and incomplete_groups == 0
        and failed_correctness_groups == 0
    )
    if require_complete and not complete:
        raise ValueError(
            "publication result set is incomplete: "
            f"missing_executions={len(missing)} "
            f"incomplete_groups={incomplete_groups} "
            f"failed_correctness_groups={failed_correctness_groups}"
        )
    status = "FAIL" if failed_correctness_groups else ("PASS" if complete else "PARTIAL")
    capacity_exclusion_rows = [dict(row) for row in capacity_exclusion_records]
    capacity_exclusion_rows.sort(key=lambda row: str(row.get("execution_id", "")))
    return {
        "schema_version": 1,
        "analysis_id": "large_graph_publication_results_v1",
        "status": status,
        "observed_executions": len(observed),
        "expected_executions": len(expected),
        "capacity_excluded_executions": len(capacity_exclusion_records),
        "contract_executions": len(expected) + len(capacity_exclusion_records),
        "duplicate_executions": sum(count - 1 for count in duplicate_counts.values()),
        "transition_invalidated_execution_ids": sorted(
            execution_id
            for execution_id, rows in invalidated_results.items()
            if rows and execution_id not in by_execution
        ),
        "complete_triplets": sum(
            bool(row["complete_triplet"]) for row in correctness_groups
        ),
        "incomplete_triplets": incomplete_groups,
        "failed_correctness_groups": failed_correctness_groups,
        "missing_execution_ids": missing,
        "unexpected_execution_ids": unexpected,
        "execution_coverage_rows": execution_coverage_rows,
        "capacity_exclusion_rows": capacity_exclusion_rows,
        "system_rows": system_rows,
        "component_activity_rows": activity_rows,
        "pair_rows": pair_rows,
        "correctness_groups": correctness_groups,
        "superseded_result_rows": superseded_result_rows,
    }


def load_case_results(roots: Sequence[Path]) -> list[dict[str, Any]]:
    paths: set[Path] = set()
    for root in roots:
        direct = root.resolve() / "case_result.json"
        if direct.is_file():
            paths.add(direct)
        paths.update(root.resolve().glob("runs/*/case_result.json"))
    return [json.loads(path.read_text(encoding="ascii")) for path in sorted(paths)]


def load_case_results_by_system(
    selections: Sequence[tuple[str, Path]],
) -> list[dict[str, Any]]:
    """Load only the named architecture from each evidence root."""

    results: list[dict[str, Any]] = []
    for system, root in selections:
        if system not in PUBLICATION_RESULT_SYSTEMS:
            raise ValueError(f"unknown publication result system: {system}")
        results.extend(
            result
            for result in load_case_results([root])
            if result.get("case", {}).get("system") == system
        )
    return results


def expected_execution_ids(manifests: Sequence[Path]) -> set[str]:
    return set(expected_execution_metadata(manifests))


def _command_option(command: Sequence[Any], option: str) -> str:
    values = [str(value) for value in command]
    try:
        index = values.index(option)
    except ValueError as error:
        raise ValueError(f"campaign job lacks {option}") from error
    if index + 1 >= len(values):
        raise ValueError(f"campaign job lacks a value for {option}")
    return values[index + 1]


def expected_execution_metadata(
    manifests: Sequence[Path],
) -> dict[str, dict[str, Any]]:
    """Load human-readable metadata for every frozen physical execution."""

    expected: dict[str, dict[str, Any]] = {}
    for path in manifests:
        payload = json.loads(path.read_text(encoding="ascii"))
        views = payload.get("execution_views")
        if not isinstance(views, Mapping):
            raise ValueError(f"campaign manifest lacks execution_views: {path}")
        jobs = payload.get("jobs")
        if not isinstance(jobs, list):
            raise ValueError(f"campaign manifest lacks jobs: {path}")
        by_execution: dict[str, Mapping[str, Any]] = {}
        for job in jobs:
            if not isinstance(job, Mapping):
                raise ValueError(f"campaign manifest has invalid job: {path}")
            execution_id = str(job.get("job_id", "")).rsplit(".", 1)[-1]
            if execution_id in by_execution:
                raise ValueError(f"campaign manifest repeats execution: {execution_id}")
            by_execution[execution_id] = job
        for raw_execution_id, raw_views in views.items():
            execution_id = str(raw_execution_id)
            job = by_execution.get(execution_id)
            if job is None:
                raise ValueError(
                    f"campaign execution lacks a physical job: {execution_id}"
                )
            command = job.get("command")
            if not isinstance(command, list):
                raise ValueError(f"campaign job lacks command: {execution_id}")
            logical_views = (
                [str(value) for value in raw_views]
                if isinstance(raw_views, list)
                else [str(raw_views)]
            )
            row = {
                "execution_id": execution_id,
                "dataset_id": str(job.get("dataset_id", "")),
                "algorithm": str(job.get("algorithm", "")),
                "scenario": _command_option(command, "--scenario"),
                "batch_size": int(_command_option(command, "--batch-size")),
                "system": str(job.get("system", "")),
                "tier": str(job.get("tier", "")),
                "logical_views": "+".join(sorted(set(logical_views))),
                "campaign_ids": str(payload.get("campaign_id", "")),
                "estimated_rss_gib": float(job.get("estimated_rss_gib", 0.0)),
            }
            previous = expected.get(execution_id)
            if previous is None:
                expected[execution_id] = row
                continue
            identity_keys = (
                "dataset_id",
                "algorithm",
                "scenario",
                "batch_size",
                "system",
            )
            if any(previous[key] != row[key] for key in identity_keys):
                raise ValueError(
                    f"campaign manifests disagree on execution: {execution_id}"
                )
            previous["logical_views"] = "+".join(
                sorted(
                    set(str(previous["logical_views"]).split("+"))
                    | set(str(row["logical_views"]).split("+"))
                )
            )
            previous["campaign_ids"] = "+".join(
                sorted(
                    set(str(previous["campaign_ids"]).split("+"))
                    | set(str(row["campaign_ids"]).split("+"))
                )
            )
    return expected


def capacity_exclusion_metadata(
    manifests: Sequence[Path],
) -> list[dict[str, Any]]:
    exclusions: dict[str, dict[str, Any]] = {}
    for path in manifests:
        payload = json.loads(path.read_text(encoding="ascii"))
        campaign_id = str(payload.get("campaign_id", ""))
        rows = payload.get("capacity_exclusions", [])
        if not isinstance(rows, list):
            raise ValueError(f"campaign capacity exclusions are invalid: {path}")
        for raw in rows:
            if not isinstance(raw, Mapping):
                raise ValueError(f"campaign capacity exclusion is invalid: {path}")
            execution_id = str(raw.get("execution_id", ""))
            if not execution_id:
                # Legacy Spine exclusions predate execution IDs and cannot be
                # joined to the physical execution coverage ledger.
                continue
            row = dict(raw)
            row["campaign_ids"] = campaign_id
            previous = exclusions.get(execution_id)
            if previous is None:
                exclusions[execution_id] = row
                continue
            comparable = {
                key: value
                for key, value in row.items()
                if key != "campaign_ids"
            }
            old_comparable = {
                key: value
                for key, value in previous.items()
                if key != "campaign_ids"
            }
            if comparable != old_comparable:
                raise ValueError(
                    f"campaigns disagree on capacity exclusion: {execution_id}"
                )
            previous["campaign_ids"] = "+".join(
                sorted(
                    set(str(previous["campaign_ids"]).split("+"))
                    | {campaign_id}
                )
            )
    return [exclusions[key] for key in sorted(exclusions)]


def write_publication_analysis(output_dir: Path, analysis: Mapping[str, Any]) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)
    compact = {key: value for key, value in analysis.items() if not key.endswith("_rows")}
    (output_dir / "summary.json").write_text(
        json.dumps(compact, indent=2, sort_keys=True) + "\n", encoding="ascii"
    )
    for name in (
        "execution_coverage_rows",
        "capacity_exclusion_rows",
        "system_rows",
        "component_activity_rows",
        "pair_rows",
        "correctness_groups",
        "superseded_result_rows",
    ):
        rows = list(analysis[name])
        path = output_dir / f"{name}.csv"
        if not rows:
            path.write_text("", encoding="ascii")
            continue
        fieldnames: list[str] = []
        seen_fields: set[str] = set()
        for row in rows:
            for field in row:
                if field not in seen_fields:
                    seen_fields.add(field)
                    fieldnames.append(field)
        with path.open("w", encoding="ascii", newline="") as stream:
            writer = csv.DictWriter(stream, fieldnames=fieldnames)
            writer.writeheader()
            writer.writerows(rows)
