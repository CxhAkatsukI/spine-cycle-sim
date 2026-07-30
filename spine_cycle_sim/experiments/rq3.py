"""RQ3 realized-work and overlap-aware Spine latency analysis."""

from __future__ import annotations

import csv
import hashlib
import json
import math
from pathlib import Path
from typing import Any, Mapping, Sequence


TEN_STAGE_KEYS = (
    "t_xfer_cycles",
    "t_reduce_cycles",
    "t_carry_cycles",
    "t_directory_cycles",
    "t_seed_cycles",
    "t_switch_cycles",
    "t_resolve_cycles",
    "t_app_cycles",
    "t_drain_cycles",
    "t_sync_cycles",
)

E2E_MODEL_FEATURES = (
    "w_sort_records",
    "w_carry_records",
    "directory_requests",
    "m_phys_records",
    "m_seed_records",
    "switch_work",
    "source_and_reactivation_work",
)


def _count(value: Any) -> int:
    if isinstance(value, bool):
        return int(value)
    if isinstance(value, (int, float)):
        return int(value)
    if isinstance(value, list):
        return sum(_count(item) for item in value)
    return 0


def _metric(metrics: Mapping[str, Any], *keys: str) -> int:
    for key in keys:
        if key in metrics and metrics[key] is not None:
            return _count(metrics[key])
    return 0


def _measurement_cycles(result: Mapping[str, Any]) -> int:
    case = result["case"]
    metrics = result.get("scalar_metrics", {})
    row = result["row"]
    if (
        case["system"] == "spine"
        and case["algorithm"] == "weighted_sssp"
        and _metric(metrics, "update_cycles") > 0
    ):
        return _metric(metrics, "update_cycles")
    return int(row["cycles"])


def _execution_metrics(result: Mapping[str, Any]) -> dict[str, Any]:
    metrics = dict(result.get("scalar_metrics", {}))
    raw_path = result.get("raw_result_path")
    raw_sha256 = result.get("raw_result_sha256")
    if not isinstance(raw_path, str) or not isinstance(raw_sha256, str):
        return metrics
    path = Path(raw_path)
    if not path.is_file():
        raise ValueError(f"RQ3 raw result is missing: {path}")
    digest = hashlib.sha256(path.read_bytes()).hexdigest()
    if digest != raw_sha256:
        raise ValueError(f"RQ3 raw result changed: {path}")
    raw = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(raw, Mapping):
        raise ValueError("RQ3 raw result must be an object")
    metrics.update(raw)
    return metrics


def _intervals(
    metrics: Mapping[str, Any],
    start_key: str,
    end_key: str,
    total: int,
    origin: int,
) -> list[tuple[int, int]]:
    starts = metrics.get(start_key, [])
    ends = metrics.get(end_key, [])
    if not isinstance(starts, list):
        starts = [starts]
    if not isinstance(ends, list):
        ends = [ends]
    if len(starts) != len(ends):
        raise ValueError(f"RQ3 interval vector mismatch: {start_key}/{end_key}")
    intervals: list[tuple[int, int]] = []
    for raw_start, raw_end in zip(starts, ends):
        start = max(0, min(total, int(raw_start) - origin))
        end = max(0, min(total, int(raw_end) - origin))
        if end < start:
            raise ValueError(f"RQ3 interval ends before it starts: {start_key}")
        if end > start:
            intervals.append((start, end))
    return intervals


def _active(intervals: Sequence[tuple[int, int]], start: int, end: int) -> bool:
    return any(left <= start and end <= right for left, right in intervals)


def _critical_path_ledger(result: Mapping[str, Any]) -> dict[str, int]:
    metrics = _execution_metrics(result)
    if not isinstance(metrics, Mapping):
        raise ValueError("RQ3 scalar_metrics must be an object")
    total = _measurement_cycles(result)
    origin = (
        _metric(metrics, "cold_cycles")
        if result["case"]["algorithm"] == "weighted_sssp"
        else 0
    )
    maintenance_start = int(metrics.get("maintenance_start_cycle", origin)) - origin
    maintenance_end = int(
        metrics.get(
            "maintenance_end_cycle",
            origin + _metric(metrics, "maintenance_cycles"),
        )
    ) - origin
    maintenance = []
    if maintenance_end > maintenance_start:
        maintenance = [
            (max(0, maintenance_start), min(total, maintenance_end))
        ]
    reader = _intervals(
        metrics,
        "reader_start_cycles_per_round",
        "reader_end_cycles_per_round",
        total,
        origin,
    )
    app = _intervals(
        metrics,
        "compute_start_cycles_per_round",
        "compute_end_cycles_per_round",
        total,
        origin,
    )
    round_starts = metrics.get("round_start_cycles", [])
    round_ends = metrics.get("round_end_cycles", [])
    sync: list[tuple[int, int]] = []
    if isinstance(round_starts, list) and isinstance(round_ends, list):
        for end, start in zip(round_ends, round_starts[1:]):
            left = max(0, min(total, int(end) - origin))
            right = max(0, min(total, int(start) - origin))
            if right > left:
                sync.append((left, right))

    boundaries = {0, total}
    for interval in maintenance + reader + app + sync:
        boundaries.update(interval)
    ordered = sorted(boundaries)
    ledger = {
        "maintenance_cycles": 0,
        "resolve_only_cycles": 0,
        "app_only_cycles": 0,
        "resolve_app_overlap_cycles": 0,
        "integrated_resolve_app_cycles": 0,
        "sync_cycles": 0,
        "other_cycles": 0,
    }
    for start, end in zip(ordered, ordered[1:]):
        width = end - start
        if width <= 0:
            continue
        if _active(maintenance, start, end):
            key = "maintenance_cycles"
        else:
            resolving = _active(reader, start, end)
            applying = _active(app, start, end)
            if resolving and applying:
                key = "resolve_app_overlap_cycles"
            elif resolving:
                key = "resolve_only_cycles"
            elif applying:
                key = "app_only_cycles"
            elif _active(sync, start, end):
                key = "sync_cycles"
            else:
                key = "other_cycles"
        ledger[key] += width
    if not reader and not app and "iteration_cycles" in metrics:
        integrated = ledger["other_cycles"]
        ledger["other_cycles"] = 0
        ledger["integrated_resolve_app_cycles"] = integrated
    if sum(ledger.values()) != total:
        raise ValueError("RQ3 critical-path ledger does not close")
    return {"total_cycles": total, **ledger}


def _covering_end(
    intervals: Sequence[tuple[int, int]], start: int, end: int
) -> int:
    return max(
        (right for left, right in intervals if left <= start and end <= right),
        default=-1,
    )


def _ten_stage_ledger(result: Mapping[str, Any]) -> dict[str, Any]:
    """Build an exclusive ten-stage critical-path ledger from direct counters."""

    metrics = _execution_metrics(result)
    total = _measurement_cycles(result)
    origin = (
        _metric(metrics, "cold_cycles")
        if result["case"]["algorithm"] == "weighted_sssp"
        else 0
    )
    maintenance_start = int(metrics.get("maintenance_start_cycle", origin)) - origin
    maintenance_end = int(
        metrics.get(
            "maintenance_end_cycle",
            origin + _metric(metrics, "maintenance_cycles"),
        )
    ) - origin
    maintenance = []
    if maintenance_end > maintenance_start:
        maintenance = [
            (max(0, maintenance_start), min(total, maintenance_end))
        ]
    maintenance_cycles = sum(end - start for start, end in maintenance)
    direct = {
        "t_xfer_cycles": _metric(metrics, "maintenance_stage_xfer_cycles"),
        "t_reduce_cycles": _metric(metrics, "maintenance_stage_reduce_cycles"),
        "t_carry_cycles": _metric(metrics, "maintenance_stage_carry_cycles"),
        "t_directory_cycles": _metric(
            metrics, "maintenance_stage_directory_cycles"
        ),
        "t_seed_cycles": _metric(metrics, "maintenance_stage_seed_cycles"),
        "t_switch_cycles": _metric(metrics, "maintenance_stage_switch_cycles"),
    }
    maintenance_supported = (
        metrics.get("maintenance_stage_ledger_closed") is True
        and all(
            key in metrics
            for key in (
                "maintenance_stage_xfer_cycles",
                "maintenance_stage_reduce_cycles",
                "maintenance_stage_carry_cycles",
                "maintenance_stage_directory_cycles",
                "maintenance_stage_seed_cycles",
                "maintenance_stage_switch_cycles",
            )
        )
        and sum(direct.values()) == maintenance_cycles
    )

    reader = _intervals(
        metrics,
        "reader_start_cycles_per_round",
        "reader_end_cycles_per_round",
        total,
        origin,
    )
    app = _intervals(
        metrics,
        "compute_start_cycles_per_round",
        "compute_end_cycles_per_round",
        total,
        origin,
    )
    round_starts = metrics.get("round_start_cycles", [])
    round_ends = metrics.get("round_end_cycles", [])
    sync: list[tuple[int, int]] = []
    if isinstance(round_starts, list) and isinstance(round_ends, list):
        for raw_end, raw_start in zip(round_ends, round_starts[1:]):
            left = max(0, min(total, int(raw_end) - origin))
            right = max(0, min(total, int(raw_start) - origin))
            if right > left:
                sync.append((left, right))

    component_supported = bool(reader or app)
    stages: dict[str, int] = {
        **direct,
        "t_resolve_cycles": 0,
        "t_app_cycles": 0,
        "t_drain_cycles": 0,
        "t_sync_cycles": 0,
    }
    boundaries = {0, total}
    for interval in maintenance + reader + app + sync:
        boundaries.update(interval)
    ordered = sorted(boundaries)
    for start, end in zip(ordered, ordered[1:]):
        width = end - start
        if width <= 0 or _active(maintenance, start, end):
            continue
        resolving = _active(reader, start, end)
        applying = _active(app, start, end)
        if resolving and applying:
            # Attribute concurrent work to the component that gates this
            # interval's completion, preserving an exclusive critical path.
            key = (
                "t_resolve_cycles"
                if _covering_end(reader, start, end)
                >= _covering_end(app, start, end)
                else "t_app_cycles"
            )
        elif resolving:
            key = "t_resolve_cycles"
        elif applying:
            key = "t_app_cycles"
        elif _active(sync, start, end):
            key = "t_sync_cycles"
        else:
            key = "t_drain_cycles"
        stages[key] += width

    supported = maintenance_supported and component_supported
    closed = supported and sum(stages.values()) == total
    if supported and not closed:
        raise ValueError("RQ3 ten-stage critical-path ledger did not close")
    return {
        **stages,
        "ten_stage_supported": supported,
        "ten_stage_ledger_closed": closed,
        "ten_stage_scope": (
            "exclusive_direct_maintenance_and_component_timestamp_critical_path"
            if supported
            else "unsupported_missing_direct_stage_or_component_timestamps"
        ),
        "frontend_dma_timed": False,
        "external_sort_timed": False,
        "residual_correction_seed_timed": False,
    }


def _case_class(case: Mapping[str, Any], metrics: Mapping[str, Any]) -> str:
    physical = int(case["update"].get("physical_records", 0))
    target = int(metrics.get("maintenance_target_level", -1))
    explicit_zero_net = (
        metrics.get("zero_net") is True
        or metrics.get("update_mode") == "zero_net_no_repair"
        or (
            physical > 0
            and "maintenance_persisted_edges" in metrics
            and _metric(metrics, "maintenance_persisted_edges") == 0
        )
    )
    if explicit_zero_net:
        return "zero_net"
    if case["scenario"] in {"delete", "weight_change"} and (
        _metric(metrics, "compute_full_recompute_reset_cycles") > 0
        or _metric(metrics, "maintenance_full_rebuild_clear_cycles") > 0
    ):
        return "deletion_fallback"
    if target > 0 or _metric(metrics, "maintenance_carry_cursor_bits_inspected") > 0:
        return "deep_carry"
    if case["algorithm"] == "thresholded_residual_pagerank":
        return "pagerank_correction"
    if case["algorithm"] == "full_pagerank":
        return "full_pagerank"
    if case["scenario"] == "insert":
        return "shallow_insertion"
    return "other"


REQUIRED_CASE_CLASSES = (
    "zero_net",
    "shallow_insertion",
    "deep_carry",
    "pagerank_correction",
    "deletion_fallback",
)


def _representative_case_rows(
    work_rows: Sequence[Mapping[str, Any]],
    latency_rows: Sequence[Mapping[str, Any]],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    latency_by_id = {row["execution_id"]: row for row in latency_rows}
    representatives: list[dict[str, Any]] = []
    coverage: list[dict[str, Any]] = []
    requirements = {
        "zero_net": "explicit zero-net execution semantics",
        "shallow_insertion": "positive insertion with target level zero",
        "deep_carry": "positive direct carry work counter",
        "pagerank_correction": "residual PageRank with positive physical work",
        "deletion_fallback": "delete or weight-change full-recompute fallback",
    }
    for case_class in REQUIRED_CASE_CLASSES:
        eligible = [row for row in work_rows if row["case_class"] == case_class]
        if case_class == "deep_carry":
            eligible = [row for row in eligible if int(row["w_carry_records"]) > 0]
        elif case_class == "pagerank_correction":
            eligible = [
                row
                for row in eligible
                if row["algorithm"] == "thresholded_residual_pagerank"
                and int(row["m_phys_records"]) > 0
            ]
        eligible.sort(
            key=lambda row: (
                int(latency_by_id[row["execution_id"]]["total_cycles"]),
                str(row["execution_id"]),
            ),
            reverse=True,
        )
        coverage.append(
            {
                "case_class": case_class,
                "status": "ready" if eligible else "missing",
                "eligible_executions": len(eligible),
                "requirement": requirements[case_class],
            }
        )
        if eligible:
            selected = eligible[0]
            representatives.append(
                {
                    **selected,
                    **{
                        key: value
                        for key, value in latency_by_id[
                            selected["execution_id"]
                        ].items()
                        if key not in selected
                    },
                    "selection_policy": "maximum_total_cycles_among_eligible",
                }
            )
    return representatives, coverage


def analyze_rq3_results(
    results: Sequence[Mapping[str, Any]],
    *,
    preferred_plugin_sha256: Sequence[str] = (),
    calibration_dataset_ids: Sequence[str] = (),
) -> dict[str, Any]:
    """Build direct work counters, exact component spans, and OLS diagnostics."""

    by_execution: dict[str, list[Mapping[str, Any]]] = {}
    for result in results:
        execution_id = str(result.get("case", {}).get("execution_id", ""))
        by_execution.setdefault(execution_id, []).append(result)
    preference = {
        plugin: index for index, plugin in enumerate(preferred_plugin_sha256)
    }
    unique_results: list[Mapping[str, Any]] = []
    for execution_id, candidates in sorted(by_execution.items()):
        candidates = sorted(
            candidates,
            key=lambda result: (
                preference.get(
                    str(result.get("plugin_sha256", "")), len(preference)
                ),
                str(result.get("plugin_sha256", "")),
                str(result.get("raw_result_path", "")),
            ),
        )
        selected = candidates[0]
        selected_plugin = str(selected.get("plugin_sha256", ""))
        for duplicate in candidates[1:]:
            if str(duplicate.get("plugin_sha256", "")) != selected_plugin:
                continue
            if (
                duplicate.get("case") != selected.get("case")
                or duplicate.get("final_state") != selected.get("final_state")
                or duplicate.get("row", {}).get("cycles")
                != selected.get("row", {}).get("cycles")
            ):
                raise ValueError(
                    f"RQ3 duplicate changed scientific result: {execution_id}"
                )
        unique_results.append(selected)

    work_rows: list[dict[str, Any]] = []
    latency_rows: list[dict[str, Any]] = []
    for result in unique_results:
        if result.get("status") != "pass" or result["case"]["system"] != "spine":
            continue
        if int(result["row"].get("architecture_correctness_mismatches", 0)) != 0:
            continue
        if int(result["row"].get("mathematical_correctness_mismatches", 0)) != 0:
            continue
        case = result["case"]
        metrics = _execution_metrics(result)
        if not isinstance(metrics, Mapping):
            raise ValueError("RQ3 scalar_metrics must be an object")
        role = result.get("rq3_role")
        if role not in {
            "synthetic_calibration",
            "trace_calibration",
            "trace_holdout",
        }:
            role = (
                "trace_calibration"
                if case["dataset_id"] in calibration_dataset_ids
                else "synthetic_calibration"
                if result["row"].get("dataset_kind") == "synthetic"
                else "trace_holdout"
            )
        common = {
            "execution_id": case["execution_id"],
            "dataset_id": case["dataset_id"],
            "algorithm": case["algorithm"],
            "scenario": case["scenario"],
            "batch_size": int(case["batch_size"]),
            "case_class": _case_class(case, metrics),
            "plugin_sha256": str(result.get("plugin_sha256", "")),
            "role": role,
        }
        construction = _metric(
            metrics, "reader_range_construction_payloads_per_round"
        )
        replay = _metric(metrics, "reader_range_replay_payloads_per_round")
        fallback = _metric(metrics, "reader_fallback_replay_edges_per_round")
        source_services = _metric(
            metrics, "reader_source_requests_per_round", "reader_source_requests"
        )
        reactivations = _metric(metrics, "frontier_out_sizes")
        descriptor_ops = sum(
            _metric(metrics, key)
            for key in (
                "maintenance_l0_writer_row_word_writes",
                "maintenance_l0_writer_mask_word_writes",
                "maintenance_l0_writer_page_base_word_writes",
                "maintenance_l0_writer_page_list_word_writes",
                "maintenance_l0_writer_page_epoch_word_writes",
                "maintenance_carry_writer_row_word_writes",
                "maintenance_carry_writer_mask_word_writes",
                "maintenance_carry_writer_page_base_word_writes",
                "maintenance_carry_writer_page_list_word_writes",
                "maintenance_carry_writer_page_epoch_word_writes",
            )
        )
        touched_pages = sum(
            _metric(metrics, key)
            for key in (
                "maintenance_carry_cursor_pages_visited",
                "maintenance_l0_writer_bitmap_page_writes",
                "maintenance_carry_writer_bitmap_page_writes",
            )
        )
        work = {
            **common,
            "delta_user_mutations": int(case["update"].get("user_mutations", 0)),
            "w_sort_records": int(case["update"].get("physical_records", 0)),
            "w_carry_records": _metric(
                metrics, "maintenance_carry_payload_reads"
            )
            + _metric(metrics, "maintenance_carry_merge_inputs")
            + _metric(metrics, "maintenance_carry_outputs"),
            "w_carry_cursor_bits": _metric(
                metrics, "maintenance_carry_cursor_bits_inspected"
            ),
            "directory_requests": _metric(
                metrics, "maintenance_target_selector_metadata_reads"
            )
            + _metric(metrics, "maintenance_family_directory_word_reads"),
            "m_phys_records": _metric(
                metrics,
                "processed_edges_per_round",
                "reader_edges_total",
                "compute_edges_total",
                "reader_edges",
                "compute_edges",
            )
            or max(construction, replay, fallback),
            "m_seed_records": _metric(metrics, "maintenance_dirty_unique_sources"),
            "touched_pages": touched_pages,
            "descriptor_operations": descriptor_ops,
            "source_services": source_services,
            "reactivations": reactivations,
            "resolve_records": construction + fallback,
            "apply_records": replay + fallback,
            "carry_wait_cycles": _metric(
                metrics,
                "maintenance_carry_refill_wait_cycles",
                "maintenance_carry_cursor_refill_cycles",
            )
            + _metric(metrics, "maintenance_carry_writer_memory_wait_cycles"),
            "directory_cycles": _metric(
                metrics, "maintenance_target_selector_cycles"
            ),
            "seed_schedule_cycles": _metric(
                metrics, "maintenance_candidate_publication_rtl_min_cycles"
            )
            + _metric(metrics, "maintenance_candidate_list_schedule_cycles"),
            "switch_wait_cycles": _metric(
                metrics, "maintenance_l0_writer_memory_wait_cycles"
            )
            + _metric(metrics, "maintenance_carry_writer_memory_wait_cycles"),
            "resolve_active_cycles": _metric(
                metrics, "reader_active_cycles_per_round", "reader_cycles"
            ),
            "app_active_cycles": _metric(
                metrics, "compute_active_cycles_per_round", "compute_cycles"
            ),
            "carry_counter_supported": any(
                key in metrics
                for key in (
                    "maintenance_carry_cursor_bits_inspected",
                    "maintenance_carry_new_batch_reads",
                    "maintenance_carry_merge_inputs",
                    "maintenance_carry_outputs",
                )
            ),
            "directory_counter_supported": (
                "maintenance_target_selector_metadata_reads" in metrics
                and "maintenance_target_selector_cycles" in metrics
            ),
            "physical_timing_supported": any(
                key in metrics
                for key in (
                    "reader_active_cycles_per_round",
                    "compute_active_cycles_per_round",
                    "reader_cycles",
                    "compute_cycles",
                )
            ),
            "seed_counter_supported": (
                "maintenance_dirty_unique_sources" in metrics
                and "maintenance_candidate_publication_rtl_min_cycles" in metrics
            ),
            "switch_counter_supported": (
                "maintenance_l0_writer_memory_wait_cycles" in metrics
            ),
            "sync_counter_supported": (
                isinstance(metrics.get("round_start_cycles"), list)
                and isinstance(metrics.get("round_end_cycles"), list)
            ),
            "counter_scope": "direct_execution_counters_nonexclusive_cycles",
        }
        ledger = _critical_path_ledger(result)
        ten_stage = _ten_stage_ledger(result)
        work_rows.append(
            {
                **work,
                "switch_work": touched_pages + descriptor_ops,
                "source_and_reactivation_work": source_services + reactivations,
                "ten_stage_counter_supported": ten_stage["ten_stage_supported"],
            }
        )
        latency_rows.append(
            {
                **common,
                **ledger,
                **ten_stage,
                "ledger_resolution": (
                    "component_timestamps"
                    if _metric(metrics, "reader_start_cycles_per_round")
                    or _metric(metrics, "compute_start_cycles_per_round")
                    else "integrated_iteration_span"
                    if "iteration_cycles" in metrics
                    else "maintenance_plus_unclassified"
                ),
                "ledger_scope": "exclusive_overlap_aware_critical_path",
                "ledger_closed": sum(
                    value for key, value in ledger.items() if key != "total_cycles"
                )
                == ledger["total_cycles"],
            }
        )

    work_rows.sort(key=lambda row: str(row["execution_id"]))
    latency_rows.sort(key=lambda row: str(row["execution_id"]))
    latency_by_id = {row["execution_id"]: row for row in latency_rows}
    regression_specs = {
        "sort_frontend": (
            "w_sort_records",
            "t_xfer_reduce_cycles",
            "ten_stage_counter_supported",
        ),
        "carry": (
            "w_carry_records",
            "t_carry_cycles",
            "ten_stage_counter_supported",
        ),
        "directory": (
            "directory_requests",
            "t_directory_cycles",
            "ten_stage_counter_supported",
        ),
        "physical_resolve_apply": (
            "m_phys_records",
            "t_resolve_app_cycles",
            "ten_stage_counter_supported",
        ),
        "seed": (
            "m_seed_records",
            "t_seed_cycles",
            "ten_stage_counter_supported",
        ),
        "switch": (
            "switch_work",
            "t_switch_cycles",
            "ten_stage_counter_supported",
        ),
        "drain": (
            "source_and_reactivation_work",
            "t_drain_cycles",
            "ten_stage_counter_supported",
        ),
    }
    fit_rows: list[dict[str, Any]] = []
    augmented: list[dict[str, Any]] = []
    for row in work_rows:
        latency = latency_by_id[row["execution_id"]]
        augmented.append(
            {
                **row,
                "resolve_app_active_cycles": row["resolve_active_cycles"]
                + row["app_active_cycles"],
                "switch_work": row["touched_pages"]
                + row["descriptor_operations"],
                "source_and_reactivation_work": row["source_services"]
                + row["reactivations"],
                "sync_cycles": latency["sync_cycles"],
                "t_xfer_reduce_cycles": latency["t_xfer_cycles"]
                + latency["t_reduce_cycles"],
                "t_carry_cycles": latency["t_carry_cycles"],
                "t_directory_cycles": latency["t_directory_cycles"],
                "t_seed_cycles": latency["t_seed_cycles"],
                "t_switch_cycles": latency["t_switch_cycles"],
                "t_resolve_app_cycles": latency["t_resolve_cycles"]
                + latency["t_app_cycles"],
                "t_drain_cycles": latency["t_drain_cycles"],
                "total_cycles": latency["total_cycles"],
            }
        )
    for role in ("all", "calibration", "trace_holdout"):
        selected = (
            augmented
            if role == "all"
            else [
                row
                for row in augmented
                if (
                    row["role"] in {"synthetic_calibration", "trace_calibration"}
                    if role == "calibration"
                    else row["role"] == role
                )
            ]
        )
        for mechanism, (x_key, y_key, support_key) in regression_specs.items():
            fit = linear_fit(
                [
                    (float(row[x_key]), float(row[y_key]))
                    for row in selected
                    if row[support_key]
                    and (
                        mechanism not in {"carry", "seed", "drain"}
                        or float(row[x_key]) > 0.0
                    )
                ]
            )
            fit_rows.append(
                {
                    "role": role,
                    "mechanism": mechanism,
                    "x_metric": x_key,
                    "y_metric": y_key,
                    "support_metric": support_key,
                    **fit,
                }
            )
    representative_rows, coverage_rows = _representative_case_rows(
        [row for row in work_rows if row["ten_stage_counter_supported"]],
        [row for row in latency_rows if row["ten_stage_supported"]],
    )
    e2e_model, e2e_prediction_rows, e2e_metric_rows = fit_e2e_cost_model(
        augmented
    )
    return {
        "schema_version": 2,
        "analysis_id": "spine_rq3_realized_work_v2",
        "preferred_plugin_sha256": list(preferred_plugin_sha256),
        "calibration_dataset_ids": list(calibration_dataset_ids),
        "e2e_model": e2e_model,
        "work_rows": work_rows,
        "latency_rows": latency_rows,
        "regression_rows": fit_rows,
        "e2e_prediction_rows": e2e_prediction_rows,
        "e2e_metric_rows": e2e_metric_rows,
        "representative_rows": representative_rows,
        "coverage_rows": coverage_rows,
    }


def linear_fit(points: Sequence[tuple[float, float]]) -> dict[str, Any]:
    finite = [(x, y) for x, y in points if math.isfinite(x) and math.isfinite(y)]
    if len(finite) < 2:
        return {"samples": len(finite), "slope": None, "intercept": None, "r2": None}
    mean_x = sum(x for x, _ in finite) / len(finite)
    mean_y = sum(y for _, y in finite) / len(finite)
    ss_x = sum((x - mean_x) ** 2 for x, _ in finite)
    if ss_x == 0:
        return {"samples": len(finite), "slope": None, "intercept": None, "r2": None}
    slope = sum((x - mean_x) * (y - mean_y) for x, y in finite) / ss_x
    intercept = mean_y - slope * mean_x
    residual = sum((y - (intercept + slope * x)) ** 2 for x, y in finite)
    total = sum((y - mean_y) ** 2 for _, y in finite)
    r2 = 1.0 if total == 0 and residual == 0 else (1.0 - residual / total if total else None)
    return {
        "samples": len(finite),
        "slope": slope,
        "intercept": intercept,
        "r2": r2,
    }


def _prediction_metrics(
    rows: Sequence[Mapping[str, Any]], role: str
) -> dict[str, Any]:
    selected = [row for row in rows if row["model_role"] == role]
    if not selected:
        return {
            "role": role,
            "samples": 0,
            "r2": None,
            "mape_percent": None,
            "max_ape_percent": None,
        }
    observed = [float(row["observed_cycles"]) for row in selected]
    predicted = [float(row["predicted_cycles"]) for row in selected]
    mean = sum(observed) / len(observed)
    residual_ss = sum(
        (actual - estimate) ** 2
        for actual, estimate in zip(observed, predicted, strict=True)
    )
    total_ss = sum((actual - mean) ** 2 for actual in observed)
    r2 = 1.0 - residual_ss / total_ss if total_ss else None
    errors = [float(row["absolute_percent_error"]) for row in selected]
    return {
        "role": role,
        "samples": len(selected),
        "r2": r2,
        "mape_percent": sum(errors) / len(errors),
        "max_ape_percent": max(errors),
    }


def fit_e2e_cost_model(
    rows: Sequence[Mapping[str, Any]],
) -> tuple[dict[str, Any], list[dict[str, Any]], list[dict[str, Any]]]:
    """Fit a calibration-only nonnegative realized-work cost model."""

    import numpy as np

    calibration_roles = {"synthetic_calibration", "trace_calibration"}
    calibration = [row for row in rows if row["role"] in calibration_roles]
    columns = ("fixed_cycles", *E2E_MODEL_FEATURES)
    if len(calibration) < len(columns):
        return (
            {
                "status": "insufficient_calibration_rows",
                "fit_method": "nonnegative_coordinate_descent",
                "features": list(E2E_MODEL_FEATURES),
                "calibration_samples": len(calibration),
                "required_samples": len(columns),
            },
            [],
            [],
        )

    matrix = np.asarray(
        [
            [1.0, *(float(row[key]) for key in E2E_MODEL_FEATURES)]
            for row in calibration
        ],
        dtype=float,
    )
    target = np.asarray(
        [float(row["total_cycles"]) for row in calibration], dtype=float
    )
    scales = np.maximum(np.max(np.abs(matrix), axis=0), 1.0)
    normalized = matrix / scales
    coefficients = np.zeros(normalized.shape[1], dtype=float)
    residual = target.copy()
    iterations = 0
    for iterations in range(1, 50_001):
        max_change = 0.0
        for index in range(normalized.shape[1]):
            column = normalized[:, index]
            denominator = float(column @ column)
            if denominator == 0.0:
                continue
            updated = max(
                0.0,
                coefficients[index] + float(column @ residual) / denominator,
            )
            change = updated - coefficients[index]
            if change:
                coefficients[index] = updated
                residual -= column * change
                max_change = max(max_change, abs(change))
        if max_change <= 1.0e-10 * max(1.0, float(np.max(coefficients))):
            break
    unscaled = coefficients / scales
    rank = int(np.linalg.matrix_rank(matrix))
    prediction_rows: list[dict[str, Any]] = []
    for row in rows:
        vector = np.asarray(
            [1.0, *(float(row[key]) for key in E2E_MODEL_FEATURES)], dtype=float
        )
        predicted = max(0.0, float(vector @ unscaled))
        observed = float(row["total_cycles"])
        prediction_rows.append(
            {
                "execution_id": row["execution_id"],
                "dataset_id": row["dataset_id"],
                "algorithm": row["algorithm"],
                "case_class": row["case_class"],
                "role": row["role"],
                "model_role": (
                    "calibration" if row["role"] in calibration_roles else row["role"]
                ),
                "observed_cycles": observed,
                "predicted_cycles": predicted,
                "residual_cycles": observed - predicted,
                "absolute_percent_error": (
                    abs(observed - predicted) / observed * 100.0
                    if observed
                    else 0.0
                ),
            }
        )
    metric_rows = [
        _prediction_metrics(prediction_rows, role)
        for role in ("calibration", "trace_holdout")
    ]
    return (
        {
            "status": "fit",
            "fit_method": "nonnegative_coordinate_descent",
            "features": list(E2E_MODEL_FEATURES),
            "columns": list(columns),
            "coefficients": {
                name: float(value)
                for name, value in zip(columns, unscaled, strict=True)
            },
            "calibration_samples": len(calibration),
            "matrix_rank": rank,
            "full_rank": rank == len(columns),
            "iterations": iterations,
            "holdout_rows_are_never_used_for_fit": True,
        },
        prediction_rows,
        metric_rows,
    )


def write_rq3_analysis(output_dir: Path, analysis: Mapping[str, Any]) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)
    summary = {key: value for key, value in analysis.items() if not key.endswith("_rows")}
    summary["work_rows"] = len(analysis["work_rows"])
    summary["latency_rows"] = len(analysis["latency_rows"])
    (output_dir / "rq3_summary.json").write_text(
        json.dumps(summary, indent=2, sort_keys=True) + "\n", encoding="ascii"
    )
    (output_dir / "rq3_e2e_model.json").write_text(
        json.dumps(analysis["e2e_model"], indent=2, sort_keys=True) + "\n",
        encoding="ascii",
    )
    for key in (
        "work_rows",
        "latency_rows",
        "regression_rows",
        "e2e_prediction_rows",
        "e2e_metric_rows",
        "representative_rows",
        "coverage_rows",
    ):
        rows = list(analysis[key])
        path = output_dir / f"rq3_{key}.csv"
        if not rows:
            path.write_text("", encoding="ascii")
            continue
        with path.open("w", encoding="ascii", newline="") as stream:
            writer = csv.DictWriter(stream, fieldnames=list(rows[0]))
            writer.writeheader()
            writer.writerows(rows)
