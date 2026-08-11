#!/usr/bin/env python3
"""Build component-cycle and request/byte/FIFO ledgers for current FPGA evidence.

Hardware event intervals are retained as separate observations because reader,
compute, adapter, and downstream intervals overlap.  The script never sums
those intervals into a total.  Simulator rows are admitted only after their
correctness and protocol ledgers pass.
"""

from __future__ import annotations

import argparse
import csv
from dataclasses import asdict
import hashlib
import json
from pathlib import Path
import statistics
import sys
from typing import Any, Iterable

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from spine_cycle_sim.calibration.current_fpga import (  # noqa: E402
    CurrentFPGAComponentRecord,
    component_prediction_rows,
    fit_component_scale,
)
from spine_cycle_sim.calibration.frozen import load_frozen_scale_models  # noqa: E402
from spine_cycle_sim.experiments.memory_traffic import (  # noqa: E402
    memory_traffic_metrics,
    phase_memory_metrics,
)


DEFAULT_CASES = ROOT / "configs/contracts/evaluation_refresh_fpga_cases_v2.json"
DEFAULT_CONTRACT = ROOT / "configs/contracts/evaluation_refresh_fpga_calibration_v3.json"
DEFAULT_OUT = ROOT / "docs/evaluation_refresh_20260810/calibration"
ARCHITECTURES = ("spine", "grasu_regraph")
GRASU_FIFO_DEPTH_FIELDS = {
    "source_cache_request_fifo_max_occupancy": (
        "regraph_source_cache_request_fifo_depth"
    ),
    "source_cache_response_fifo_max_occupancy": (
        "regraph_source_cache_response_fifo_depth"
    ),
    "gather_merger_fifo_max_occupancy": "regraph_gather_merger_fifo_depth",
    "merger_apply_fifo_max_occupancy": "regraph_merger_apply_fifo_depth",
    "apply_wrapper_fifo_max_occupancy": "regraph_apply_wrapper_fifo_depth",
}


def read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        while chunk := source.read(1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()


def write_json(path: Path, payload: dict[str, Any]) -> None:
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def write_csv(path: Path, rows: list[dict[str, object]]) -> None:
    if not rows:
        return
    with path.open("w", encoding="utf-8", newline="") as sink:
        writer = csv.DictWriter(sink, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)


def parse_key_value_line(line: str, prefix: str) -> dict[str, str]:
    if not line.startswith(prefix + " "):
        raise ValueError(f"line does not start with {prefix!r}")
    parsed: dict[str, str] = {}
    for token in line[len(prefix) + 1 :].strip().split():
        if "=" not in token:
            continue
        key, value = token.split("=", 1)
        parsed[key] = value
    if not parsed:
        raise ValueError(f"empty timing record for {prefix!r}")
    return parsed


def unique_prefixed_record(path: Path, prefix: str) -> dict[str, str]:
    matches = {
        line.strip()
        for line in path.read_text(encoding="utf-8", errors="replace").splitlines()
        if line.startswith(prefix + " ")
    }
    if len(matches) != 1:
        raise ValueError(f"expected one unique {prefix} record in {path}, got {len(matches)}")
    return parse_key_value_line(next(iter(matches)), prefix)


def prefixed_records(path: Path, prefix: str) -> list[dict[str, str]]:
    return [
        parse_key_value_line(line.strip(), prefix)
        for line in path.read_text(encoding="utf-8", errors="replace").splitlines()
        if line.startswith(prefix + " ")
    ]


def raw_paths_from_manifests(hardware_dir: Path) -> set[Path]:
    paths: set[Path] = set()
    for manifest in hardware_dir.glob("*raw_evidence.sha256"):
        for line in manifest.read_text(encoding="utf-8").splitlines():
            fields = line.split(maxsplit=1)
            if len(fields) == 2:
                path = Path(fields[1])
                if path.is_file():
                    paths.add(path.resolve())
    return paths


def discover_hardware_logs(
    hardware_root: Path,
    algorithm_spec: dict[str, Any],
    dataset: str,
    architecture: str,
) -> list[Path]:
    case = f"{dataset}_{algorithm_spec['hardware_case_suffix']}"
    hardware_dir = hardware_root / algorithm_spec["hardware_directory"]
    candidates = raw_paths_from_manifests(hardware_dir)
    for raw_root in algorithm_spec.get("hardware_raw_roots", []):
        case_dir = Path(raw_root) / case
        if case_dir.is_dir():
            candidates.update(path.resolve() for path in case_dir.rglob("*.log"))
    if architecture == "spine":
        selected = [
            path
            for path in candidates
            if f"/{case}/spine/" in str(path) and path.name.startswith("dynamic_")
        ]
    else:
        selected = [
            path
            for path in candidates
            if f"/{case}/grasu_regraph/" in str(path) and path.name == "run.log"
        ]
    return sorted(set(selected))


def run_directory(
    simulation_root: Path,
    algorithm_spec: dict[str, Any],
    dataset: str,
    architecture: str,
) -> Path:
    directories = algorithm_spec.get("simulation_directories", {})
    directory = directories.get(architecture, algorithm_spec["simulation_directory"])
    return simulation_root / "runs_current_v1" / dataset / architecture / directory


def load_admitted_result(run_dir: Path) -> tuple[dict[str, Any], Path, Path]:
    result_path = run_dir / "result.json"
    manifest_path = next(
        (
            path
            for path in (
                run_dir / "run_manifest.json",
                run_dir / "summary.json",
                run_dir / "manifest.json",
            )
            if path.is_file()
        ),
        run_dir / "run_manifest.json",
    )
    if not result_path.is_file() or not manifest_path.is_file():
        raise FileNotFoundError(run_dir)
    result = read_json(result_path)
    manifest = read_json(manifest_path)
    if result.get("success") is not True or manifest.get("status") != "PASS":
        raise ValueError(f"simulator admission failed: {run_dir}")
    if manifest.get("admitted", True) is not True:
        raise ValueError(f"simulator row not admitted: {run_dir}")
    for key in (
        "correctness_mismatches",
        "architecture_correctness_mismatches",
        "mathematical_correctness_mismatches",
    ):
        if int(result.get(key, 0)) != 0:
            raise ValueError(f"nonzero {key}: {run_dir}")
    return result, result_path, manifest_path


def evidence_identity(
    result: dict[str, Any], manifest: dict[str, Any], fields: tuple[str, ...]
) -> str:
    for source in (manifest, result):
        for field in fields:
            value = source.get(field)
            if isinstance(value, str) and value:
                return value
    raise ValueError(f"simulator evidence does not identify any of {fields}")


def median_float(records: Iterable[dict[str, str]], key: str) -> float:
    values = [float(record[key]) for record in records]
    if not values or min(values) < 0:
        raise ValueError(f"missing or negative hardware field {key}")
    return statistics.median(values)


def span_sum(result: dict[str, Any], start_key: str, end_key: str) -> float:
    starts = [float(value) for value in result.get(start_key, [])]
    ends = [float(value) for value in result.get(end_key, [])]
    if len(starts) != len(ends):
        raise ValueError(f"mismatched simulator intervals: {start_key}/{end_key}")
    return sum(end - start for start, end in zip(starts, ends))


def component_samples(
    architecture: str,
    algorithm: str,
    result: dict[str, Any],
    hardware_records: list[dict[str, str]],
    clock_mhz: float,
) -> list[tuple[str, float, float, str]]:
    samples: list[tuple[str, float, float, str]] = []
    if architecture == "spine":
        samples.append(
            (
                "maintenance",
                float(result["maintenance_cycles"]),
                median_float(hardware_records, "maintenance_kernel_ms") * clock_mhz * 1000.0,
                "median routed maintenance kernel event; nonoverlapping with iterative kernel span",
            )
        )
        reader = span_sum(result, "reader_start_cycles_per_round", "reader_end_cycles_per_round")
        compute = span_sum(result, "compute_start_cycles_per_round", "compute_end_cycles_per_round")
        if reader > 0 and median_float(hardware_records, "reader_ms") > 0:
            samples.append(
                (
                    "reader_event",
                    reader,
                    median_float(hardware_records, "reader_ms") * clock_mhz * 1000.0,
                    "median routed reader event envelope across all rounds; overlaps compute",
                )
            )
        if compute > 0 and median_float(hardware_records, "compute_ms") > 0:
            samples.append(
                (
                    "compute_event",
                    compute,
                    median_float(hardware_records, "compute_ms") * clock_mhz * 1000.0,
                    "median routed compute event envelope across all rounds; overlaps reader",
                )
            )
        iterative = float(result["cycles"]) - float(result["maintenance_cycles"])
        if iterative > 0 and median_float(hardware_records, "kernel_span_ms") > 0:
            samples.append(
                (
                    "iterative_kernel_span",
                    iterative,
                    median_float(hardware_records, "kernel_span_ms") * clock_mhz * 1000.0,
                    "median routed first-reader-start to last-reader/compute-end span; contains overlap",
                )
            )
        return samples

    update_field = "update_ms" if algorithm == "thresholded_residual_pagerank" else "grasu_ms"
    samples.append(
        (
            "update_event",
            float(result["update_cycles"]),
            median_float(hardware_records, update_field) * clock_mhz * 1000.0,
            f"median routed G+R {update_field} event; downstream events may overlap it",
        )
    )
    if float(result.get("compute_cycles", 0)) > 0:
        samples.append(
            (
                "downstream_hbm_event",
                float(result["compute_cycles"]),
                median_float(hardware_records, "hbm_ms") * clock_mhz * 1000.0,
                "median routed terminal HBM event interval; diagnostic only and overlapping upstream events",
            )
        )
    return samples


def list_equal(left: Any, right: Any) -> bool:
    return isinstance(left, list) and isinstance(right, list) and left == right


def spine_structural_work_row(
    algorithm: str,
    dataset: str,
    role: str,
    result: dict[str, Any],
    result_path: Path,
    hardware_logs: list[Path],
    timing_records: list[dict[str, str]],
) -> dict[str, object]:
    if algorithm == "weighted_sssp":
        simulator_iterations = int(result["rounds"])
        simulator_tasks = [int(value) for value in result["reader_range_tasks_per_round"]]
        simulator_edges = [int(value) for value in result["processed_edges_per_round"]]
    elif algorithm == "connected_components":
        simulator_iterations = int(result["iterations"])
        simulator_tasks = [
            int(value) for value in result["reader_range_tasks_per_iteration"]
        ]
        simulator_edges = [int(value) for value in result["reader_edges_per_iteration"]]
    else:
        simulator_iterations = int(result["iterations"])
        simulator_tasks = [
            int(value)
            for value in result.get("reader_range_tasks_per_iteration", [])
        ]
        simulator_edges = [
            int(value) for value in result.get("reader_edges_per_iteration", [])
        ]

    hardware_iterations_per_run = [int(record["iterations"]) for record in timing_records]
    hardware_tasks_per_run: list[list[int]] = []
    hardware_edges_per_run: list[list[int]] = []
    for path in hardware_logs:
        iteration_records = prefixed_records(path, "KERNEL_PAIR_RESULT")
        hardware_tasks_per_run.append(
            [int(record["task_count"]) for record in iteration_records]
        )
        hardware_edges_per_run.append(
            [int(record["processed_edges"]) for record in iteration_records]
        )

    expected_iterations = [simulator_iterations] * len(hardware_logs)
    expected_tasks = [simulator_tasks] * len(hardware_logs)
    expected_edges = [simulator_edges] * len(hardware_logs)
    checks = {
        "hardware_runs_repeatable_iterations": len(set(hardware_iterations_per_run)) == 1,
        "hardware_runs_repeatable_tasks": all(
            row == hardware_tasks_per_run[0] for row in hardware_tasks_per_run
        ),
        "hardware_runs_repeatable_edges": all(
            row == hardware_edges_per_run[0] for row in hardware_edges_per_run
        ),
        "simulator_hardware_iterations_match": hardware_iterations_per_run
        == expected_iterations,
        "simulator_hardware_task_count_match": hardware_tasks_per_run == expected_tasks,
        "simulator_hardware_processed_edges_match": hardware_edges_per_run
        == expected_edges,
    }
    passed = all(checks.values())
    return {
        "architecture": "spine",
        "algorithm": algorithm,
        "dataset": dataset,
        "role": role,
        "status": "PASS" if passed else "FAIL",
        "simulator_iterations": simulator_iterations,
        "simulator_task_count_per_iteration": simulator_tasks,
        "simulator_processed_edges_per_iteration": simulator_edges,
        "hardware_iterations_per_run": hardware_iterations_per_run,
        "hardware_task_count_per_iteration_per_run": hardware_tasks_per_run,
        "hardware_processed_edges_per_iteration_per_run": hardware_edges_per_run,
        "checks": checks,
        "hardware_observation_scope": (
            "routed Spine KERNEL_PAIR_RESULT counters; G+R routed hosts do not expose "
            "equivalent per-round task/edge counters"
        ),
        "simulator_result": str(result_path.resolve()),
        "simulator_result_sha256": sha256_file(result_path),
    }


def memory_ledger_row(
    architecture: str,
    algorithm: str,
    dataset: str,
    role: str,
    result: dict[str, Any],
    result_path: Path,
    profile_parameters: dict[str, Any] | None = None,
) -> dict[str, object]:
    traffic_value = result.get("backend_traffic")
    traffic = (
        traffic_value.get("combined", {})
        if isinstance(traffic_value, dict)
        else {}
    )
    requests = int(traffic.get("requests", -1))
    backend_requests = int(result.get("backend_requests", -2))
    bytes_accepted = int(traffic.get("bytes", -1))
    request_balance = requests >= 0 and requests == backend_requests
    traffic_validation_error = ""
    try:
        memory_traffic_metrics(
            traffic_value,
            expected_requests=backend_requests,
            prefix="backend",
        )
        traffic_schema_closed = True
    except (TypeError, ValueError) as error:
        traffic_schema_closed = False
        traffic_validation_error = str(error)
    byte_balance = bytes_accepted >= 0 and request_balance and traffic_schema_closed
    checks: dict[str, bool] = {
        "backend_request_traffic_match": request_balance,
        "backend_read_write_and_locality_categories_close": traffic_schema_closed,
        "accepted_bytes_complete_at_quiescence": byte_balance,
        "memory_locality_ledger_match": result.get("memory_locality_ledger_match") is True,
        "active_edge_execution_ledger_match": result.get(
            "active_edge_execution_ledger_match", True
        )
        is True,
    }
    if architecture == "spine":
        owner_round_count = result.get("owner_round_evidence_count")
        per_round_fields = (
            "reader_source_completion_markers_per_round",
            "compute_source_completion_markers_per_round",
            "owner_round_begins_per_round",
            "owner_source_dispatches_per_round",
            "owner_source_completions_per_round",
            "owner_activation_words_per_round",
            "owner_round_finalizes_per_round",
            "owner_hbm_requests_expected_per_round",
            "owner_hbm_requests_generated_per_round",
            "owner_hbm_requests_completed_per_round",
            "owner_hbm_read_requests_per_round",
            "owner_hbm_write_requests_per_round",
            "owner_hbm_read_bytes_per_round",
            "owner_hbm_write_bytes_per_round",
            "owner_round_ledger_match_per_round",
            "owner_hbm_request_ledger_match_per_round",
            "owner_hbm_byte_ledger_match_per_round",
        )
        owner_arrays = [result.get(field) for field in per_round_fields]
        owner_evidence_reported = (
            isinstance(owner_round_count, int)
            and owner_round_count >= 0
            and all(isinstance(values, list) for values in owner_arrays)
            and all(len(values) == owner_round_count for values in owner_arrays)
        )
        owner_rows_recomputed = owner_evidence_reported
        if owner_evidence_reported:
            for round_index in range(owner_round_count):
                dispatches = int(
                    result["owner_source_dispatches_per_round"][round_index]
                )
                completions = int(
                    result["owner_source_completions_per_round"][round_index]
                )
                activation_words = int(
                    result["owner_activation_words_per_round"][round_index]
                )
                expected_requests = (
                    2 + 7 * dispatches + 6 * completions + 8 * activation_words + 9
                )
                owner_rows_recomputed = owner_rows_recomputed and all(
                    (
                        int(result["owner_round_begins_per_round"][round_index]) == 1,
                        int(result["owner_round_finalizes_per_round"][round_index]) == 1,
                        dispatches == completions,
                        int(
                            result[
                                "reader_source_completion_markers_per_round"
                            ][round_index]
                        )
                        == dispatches,
                        int(
                            result[
                                "compute_source_completion_markers_per_round"
                            ][round_index]
                        )
                        == completions,
                        int(
                            result["owner_hbm_requests_expected_per_round"][
                                round_index
                            ]
                        )
                        == expected_requests,
                        int(
                            result["owner_hbm_requests_generated_per_round"][
                                round_index
                            ]
                        )
                        == expected_requests,
                        int(
                            result["owner_hbm_requests_completed_per_round"][
                                round_index
                            ]
                        )
                        == expected_requests,
                        int(result["owner_hbm_read_requests_per_round"][round_index])
                        + int(
                            result["owner_hbm_write_requests_per_round"][round_index]
                        )
                        == expected_requests,
                        int(result["owner_hbm_read_bytes_per_round"][round_index])
                        + int(result["owner_hbm_write_bytes_per_round"][round_index])
                        == expected_requests * 8,
                    )
                )
        checks.update(
            {
                "owner_scheduler_enabled": result.get(
                    "owner_scheduler_enabled"
                )
                is True,
                "owner_round_evidence_reported": owner_evidence_reported,
                "owner_round_formula_recomputed": owner_rows_recomputed,
                "owner_round_ledger_match": result.get(
                    "owner_round_ledger_match"
                )
                is True,
                "owner_hbm_request_ledger_match": result.get(
                    "owner_hbm_request_ledger_match"
                )
                is True,
                "owner_hbm_byte_ledger_match": result.get(
                    "owner_hbm_byte_ledger_match"
                )
                is True,
                "owner_round_rows_all_pass": owner_evidence_reported
                and all(
                    int(value) == 1
                    for field in per_round_fields[-3:]
                    for value in result[field]
                ),
            }
        )
    fifo_evidence = "completion_protocol_reaches_quiescence_with_bounded_fifo_occupancy"
    if architecture == "spine" and algorithm == "weighted_sssp":
        checks.update(
            {
                "maintenance_requests_closed": int(result["maintenance_memory_requests_issued"])
                == int(result["maintenance_memory_requests_completed"]),
                "reader_requests_closed": list_equal(
                    result["reader_memory_requests_issued_per_round"],
                    result["reader_memory_requests_completed_per_round"],
                ),
                "compute_requests_closed": list_equal(
                    result["compute_memory_requests_issued_per_round"],
                    result["compute_memory_requests_completed_per_round"],
                ),
                "owner_ledger_closed": result.get("owner_ledger_closed") is True,
            }
        )
        fifo_evidence = "per-round AXIS transfer counts plus closed owner/request ledgers"
    elif architecture == "spine" and algorithm == "connected_components":
        checks.update(
            {
                "component_requests_closed": result.get("component_request_ledger_match") is True,
                "fifo_push_pop_match": result.get("fifo_ledger_match") is True,
                "owner_ledger_closed": result.get("owner_ledger_closed") is True,
            }
        )
        fifo_evidence = "explicit edge/value AXIS push-pop equality"
    elif architecture == "spine":
        checks.update(
            {
                "correction_requests_closed": result.get(
                    "residual_correction_request_ledger_closed"
                )
                is True,
                "memory_ledger_match": result.get("memory_ledger_match") is True,
                "owner_ledger_closed": result.get("owner_ledger_closed") is True,
            }
        )
        fifo_evidence = "zero-propagation correction-only row; no reader/compute AXIS payload"
    else:
        parameters = profile_parameters or {}
        update_requests = int(result.get("update_backend_requests", -1))
        compute_requests = int(result.get("compute_backend_requests", -1))
        phase_validation_error = ""
        try:
            phase_memory_metrics(
                result,
                update_key="update_backend_traffic",
                backend_requests=backend_requests,
                update_requests=update_requests,
                compute_requests=compute_requests,
            )
            phase_traffic_closed = True
        except (TypeError, ValueError) as error:
            phase_traffic_closed = False
            phase_validation_error = str(error)
        checks.update(
            {
                "phase_request_count_sum_match": update_requests >= 0
                and compute_requests >= 0
                and update_requests + compute_requests == backend_requests,
                "update_compute_traffic_decomposition_closes": phase_traffic_closed,
            }
        )
        expected = result.get("expected_backend_requests")
        if expected is not None:
            checks["expected_backend_requests_match"] = int(expected) == backend_requests
        fifo_depth_checks: dict[str, dict[str, int | bool]] = {}
        for occupancy_field, depth_field in GRASU_FIFO_DEPTH_FIELDS.items():
            occupancy = result.get(occupancy_field)
            depth = parameters.get(depth_field)
            valid = (
                isinstance(occupancy, int)
                and not isinstance(occupancy, bool)
                and isinstance(depth, int)
                and not isinstance(depth, bool)
                and depth > 0
                and 0 <= occupancy <= depth
            )
            fifo_depth_checks[occupancy_field] = {
                "occupancy": int(occupancy) if isinstance(occupancy, int) else -1,
                "profile_depth": int(depth) if isinstance(depth, int) else -1,
                "within_depth": valid,
            }
        if algorithm == "thresholded_residual_pagerank":
            for occupancy_field, depth_field in (
                ("degree_fifo_max_occupancy", "grasu_degree_fifo_depth"),
                ("degree_reorder_max_occupancy", "grasu_degree_reorder_entries"),
            ):
                occupancy = result.get(occupancy_field)
                depth = parameters.get(depth_field)
                valid = (
                    isinstance(occupancy, int)
                    and not isinstance(occupancy, bool)
                    and isinstance(depth, int)
                    and not isinstance(depth, bool)
                    and depth > 0
                    and 0 <= occupancy <= depth
                )
                fifo_depth_checks[occupancy_field] = {
                    "occupancy": (
                        int(occupancy) if isinstance(occupancy, int) else -1
                    ),
                    "profile_depth": int(depth) if isinstance(depth, int) else -1,
                    "within_depth": valid,
                }
        adapter_depth = parameters.get("regraph_pma_adapter_axis_fifo_depth")
        checks.update(
            {
                "observable_fifo_occupancies_within_frozen_depths": bool(
                    fifo_depth_checks
                )
                and all(
                    bool(row["within_depth"])
                    for row in fifo_depth_checks.values()
                ),
                "adapter_axis_finite_depth_and_backpressure_reported": (
                    isinstance(adapter_depth, int)
                    and not isinstance(adapter_depth, bool)
                    and adapter_depth > 0
                    and isinstance(result.get("axis_push_stalls"), int)
                    and not isinstance(result.get("axis_push_stalls"), bool)
                    and int(result["axis_push_stalls"]) >= 0
                ),
            }
        )
        fifo_evidence = (
            "profile-bounded downstream FIFO occupancies; adapter AXIS has a "
            "frozen finite depth and stall counter but no occupancy counter"
        )
    passed = all(checks.values())
    return {
        "architecture": architecture,
        "algorithm": algorithm,
        "dataset": dataset,
        "role": role,
        "status": "PASS" if passed else "FAIL",
        "backend_requests": backend_requests,
        "accepted_backend_bytes": bytes_accepted,
        "requests_issued_equal_completed": request_balance,
        "bytes_issued_equal_completed": byte_balance,
        "fifo_balance_or_residual_explained": passed,
        "fifo_evidence": fifo_evidence,
        "checks": checks,
        "traffic_validation_error": traffic_validation_error,
        "phase_traffic_validation_error": (
            phase_validation_error if architecture != "spine" else ""
        ),
        "fifo_depth_checks": (
            fifo_depth_checks if architecture != "spine" else {}
        ),
        "simulator_result": str(result_path.resolve()),
        "simulator_result_sha256": sha256_file(result_path),
    }


def summarize_component(rows: list[dict[str, object]]) -> dict[str, object]:
    calibration = [row for row in rows if row["role"] == "calibration"]
    holdout = [row for row in rows if row["role"] == "holdout"]
    return {
        "architecture": rows[0]["architecture"],
        "algorithm": rows[0]["algorithm"],
        "component": rows[0]["component"],
        "calibration_cases": len(calibration),
        "holdout_cases": len(holdout),
        "calibration_median_absolute_error_percent": statistics.median(
            float(row["absolute_error_percent"]) for row in calibration
        ),
        "holdout_median_absolute_error_percent": statistics.median(
            float(row["absolute_error_percent"]) for row in holdout
        ),
        "holdout_max_absolute_error_percent": max(
            float(row["absolute_error_percent"]) for row in holdout
        ),
    }


def analyze_component_records(
    records: list[CurrentFPGAComponentRecord],
    component_threshold: float,
    frozen_models: dict[tuple[str, ...], Any] | None = None,
) -> tuple[
    list[dict[str, object]],
    list[dict[str, object]],
    list[dict[str, object]],
]:
    grouped: dict[tuple[str, str, str, str], list[CurrentFPGAComponentRecord]] = {}
    for record in records:
        grouped.setdefault(
            (record.architecture, record.algorithm, record.profile_id, record.component),
            [],
        ).append(record)
    predictions: list[dict[str, object]] = []
    summaries: list[dict[str, object]] = []
    models: list[dict[str, object]] = []
    for key in sorted(grouped):
        group = grouped[key]
        if sum(row.role == "calibration" for row in group) < 2 or sum(
            row.role == "holdout" for row in group
        ) < 1:
            continue
        if frozen_models is None:
            model = fit_component_scale(group)
        else:
            model = frozen_models.get(key)
            if model is None:
                raise ValueError(f"missing frozen component model: {key}")
        group_rows = component_prediction_rows(group, model)
        summary = summarize_component(group_rows)
        summary["holdout_median_pass"] = (
            float(summary["holdout_median_absolute_error_percent"])
            <= component_threshold
        )
        predictions.extend(group_rows)
        summaries.append(summary)
        models.append(
            {
                **asdict(model),
                "profile_id": key[2],
                "fit_role": "calibration_only",
                "holdout_used_for_fit": False,
                "hardware_event_intervals_summed": False,
            }
        )
    return predictions, summaries, models


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--cases", type=Path, default=DEFAULT_CASES)
    parser.add_argument("--contract", type=Path, default=DEFAULT_CONTRACT)
    parser.add_argument("--simulation-root", type=Path)
    parser.add_argument("--hardware-root", type=Path)
    parser.add_argument("--out-dir", type=Path, default=DEFAULT_OUT)
    parser.add_argument("--allow-partial", action="store_true")
    parser.add_argument("--frozen-models-dir", type=Path)
    args = parser.parse_args()

    cases_path = args.cases.resolve()
    contract_path = args.contract.resolve()
    cases = read_json(cases_path)
    contract = read_json(contract_path)
    if cases.get("status") != "frozen" or contract.get("status") != "frozen":
        raise ValueError("case and calibration contracts must be frozen")
    if cases.get("calibration_contract_id") != contract.get("contract_id"):
        raise ValueError("case manifest and calibration contract disagree")
    plugin_path = ROOT / contract["simulator_plugin"]["path"]
    if not plugin_path.is_file() or sha256_file(plugin_path) != contract[
        "simulator_plugin"
    ]["sha256"]:
        raise ValueError("frozen simulator plugin identity mismatch")
    simulation_root = (args.simulation_root or Path(cases["default_simulation_root"])).resolve()
    hardware_root = (args.hardware_root or Path(cases["default_hardware_root"])).resolve()
    clock_mhz = float(cases["clock_mhz"])
    profile_entries = {
        (row["architecture"], row["algorithm"]): row
        for row in contract["architecture_profiles"]
    }
    profiles = {key: row["profile_id"] for key, row in profile_entries.items()}
    expected_plugin_sha256 = str(contract["simulator_plugin"]["sha256"])
    frozen_models = None
    frozen_provenance = None
    if args.frozen_models_dir:
        frozen_models, frozen_provenance = load_frozen_scale_models(
            args.frozen_models_dir,
            kind="component",
            contract_id=contract["contract_id"],
            contract_sha256=sha256_file(contract_path),
            cases_sha256=sha256_file(cases_path),
            plugin_sha256=expected_plugin_sha256,
        )
    component_records: list[CurrentFPGAComponentRecord] = []
    component_evidence: list[dict[str, object]] = []
    ledger_rows: list[dict[str, object]] = []
    structural_rows: list[dict[str, object]] = []
    missing: list[str] = []

    for algorithm, algorithm_spec in cases["algorithms"].items():
        for dataset, role in cases["roles"].items():
            for architecture in ARCHITECTURES:
                run_dir = run_directory(simulation_root, algorithm_spec, dataset, architecture)
                try:
                    result, result_path, manifest_path = load_admitted_result(run_dir)
                    logs = discover_hardware_logs(
                        hardware_root, algorithm_spec, dataset, architecture
                    )
                    if len(logs) < 3:
                        raise FileNotFoundError(f"three hardware logs for {architecture}:{algorithm}:{dataset}")
                except FileNotFoundError:
                    missing.append(f"{architecture}:{algorithm}:{dataset}")
                    if args.allow_partial:
                        continue
                    raise
                prefix = (
                    "SPINE_HW_TIMING"
                    if architecture == "spine"
                    else algorithm_spec["hardware_timing_prefix"]
                )
                hardware_records = [unique_prefixed_record(path, prefix) for path in logs]
                profile_id = profiles[(architecture, algorithm)]
                manifest = read_json(manifest_path)
                observed_profile_id = evidence_identity(
                    result, manifest, ("profile_id", "architecture_profile_id")
                )
                if observed_profile_id != profile_id:
                    raise ValueError(
                        f"profile id mismatch for {architecture}:{algorithm}:{dataset}"
                    )
                observed_profile_sha256 = evidence_identity(
                    result,
                    manifest,
                    ("profile_sha256", "architecture_profile_sha256"),
                )
                if observed_profile_sha256 != profile_entries[(architecture, algorithm)][
                    "sha256"
                ]:
                    raise ValueError(
                        f"profile hash mismatch for {architecture}:{algorithm}:{dataset}"
                    )
                if manifest.get("sst_plugin_sha256") != expected_plugin_sha256:
                    raise ValueError(
                        f"plugin hash mismatch for {architecture}:{algorithm}:{dataset}"
                    )
                if architecture == "spine":
                    structural_row = spine_structural_work_row(
                            algorithm,
                            dataset,
                            role,
                            result,
                            result_path,
                            logs,
                            hardware_records,
                        )
                    structural_row["profile_id"] = profile_id
                    structural_rows.append(structural_row)
                for component, simulator_cycles, hardware_cycles, observation in component_samples(
                    architecture, algorithm, result, hardware_records, clock_mhz
                ):
                    component_records.append(
                        CurrentFPGAComponentRecord(
                            architecture,
                            algorithm,
                            profile_id,
                            dataset,
                            role,
                            component,
                            simulator_cycles,
                            hardware_cycles,
                            observation,
                        )
                    )
                component_evidence.append(
                    {
                        "architecture": architecture,
                        "algorithm": algorithm,
                        "dataset": dataset,
                        "role": role,
                        "profile_id": profile_id,
                        "profile_sha256": observed_profile_sha256,
                        "sst_plugin_sha256": expected_plugin_sha256,
                        "simulator_result": str(result_path.resolve()),
                        "simulator_result_sha256": sha256_file(result_path),
                        "simulator_manifest": str(manifest_path.resolve()),
                        "simulator_manifest_sha256": sha256_file(manifest_path),
                        "hardware_logs": [str(path) for path in logs],
                        "hardware_log_sha256": [sha256_file(path) for path in logs],
                    }
                )
                ledger_row = memory_ledger_row(
                        architecture,
                        algorithm,
                        dataset,
                        role,
                        result,
                        result_path,
                        read_json(ROOT / profile_entries[(architecture, algorithm)]["path"])[
                            "parameters"
                        ],
                    )
                ledger_row["profile_id"] = profile_id
                ledger_rows.append(ledger_row)

    component_threshold = float(
        contract["manifest_gates"]["component_cycle"]["median_absolute_error_percent_max"]
    )
    predictions, summaries, models = analyze_component_records(
        component_records, component_threshold, frozen_models
    )

    expected_component_groups = 3 + 4 + 1 + 2 + 2 + 2
    component_pass = (
        not missing
        and len(summaries) == expected_component_groups
        and all(bool(row["holdout_median_pass"]) for row in summaries)
    )
    component_status = "PASS" if component_pass else ("INCOMPLETE" if missing else "FAIL")
    ledger_pass = not missing and ledger_rows and all(row["status"] == "PASS" for row in ledger_rows)
    ledger_status = "PASS" if ledger_pass else ("INCOMPLETE" if missing else "FAIL")
    expected_structural_rows = len(cases["algorithms"]) * len(cases["roles"])
    structural_pass = (
        not missing
        and len(structural_rows) == expected_structural_rows
        and all(row["status"] == "PASS" for row in structural_rows)
    )
    structural_status = (
        "PASS" if structural_pass else ("INCOMPLETE" if missing else "FAIL")
    )

    component_coverage: list[dict[str, object]] = []
    ledger_coverage: list[dict[str, object]] = []
    structural_coverage: list[dict[str, object]] = []
    for architecture in ARCHITECTURES:
        for algorithm in cases["algorithms"]:
            profile_id = profiles[(architecture, algorithm)]
            pair_evidence = [
                row
                for row in component_evidence
                if row["architecture"] == architecture
                and row["algorithm"] == algorithm
            ]
            component_coverage.append(
                {
                    "architecture": architecture,
                    "algorithm": algorithm,
                    "profile_id": profile_id,
                    "calibration_cases": sum(
                        row["role"] == "calibration" for row in pair_evidence
                    ),
                    "holdout_cases": sum(
                        row["role"] == "holdout" for row in pair_evidence
                    ),
                }
            )
            pair_ledgers = [
                row
                for row in ledger_rows
                if row["architecture"] == architecture
                and row["algorithm"] == algorithm
            ]
            ledger_coverage.append(
                {
                    "architecture": architecture,
                    "algorithm": algorithm,
                    "profile_id": profile_id,
                    "validation_cases": len(pair_ledgers),
                    "ledger_closed": bool(pair_ledgers)
                    and all(row["status"] == "PASS" for row in pair_ledgers),
                }
            )
            if architecture == "spine":
                pair_structural = [
                    row
                    for row in structural_rows
                    if row["algorithm"] == algorithm
                ]
                structural_coverage.append(
                    {
                        "architecture": architecture,
                        "algorithm": algorithm,
                        "profile_id": profile_id,
                        "validation_cases": len(pair_structural),
                        "ledger_closed": bool(pair_structural)
                        and all(row["status"] == "PASS" for row in pair_structural),
                        "hardware_counter_scope": (
                            "routed_iteration_range_task_processed_edge_counters"
                        ),
                    }
                )
            else:
                structural_coverage.append(
                    {
                        "architecture": architecture,
                        "algorithm": algorithm,
                        "profile_id": profile_id,
                        "validation_cases": len(pair_evidence),
                        "ledger_closed": False,
                        "hardware_counter_scope": "not_observable",
                    }
                )

    args.out_dir.mkdir(parents=True, exist_ok=True)
    write_csv(args.out_dir / "component_cycle_rows.csv", predictions)
    write_csv(args.out_dir / "component_cycle_group_summary.csv", summaries)
    write_json(
        args.out_dir / "component_cycle_models.json",
        {
            "schema_version": 1,
            "status": component_status,
            "parameters_frozen": frozen_models is not None or component_pass,
            "parameters_frozen_before_holdout": frozen_models is not None,
            "models": models,
        },
    )
    write_json(
        args.out_dir / "component_cycle_calibration.json",
        {
            "schema_version": 1,
            "gate_kind": "component_cycle",
            "contract_id": contract["contract_id"],
            "contract_sha256": sha256_file(contract_path),
            "case_contract_sha256": sha256_file(cases_path),
            "status": component_status,
            "parameters_frozen": frozen_models is not None or component_pass,
            "parameters_frozen_before_holdout": frozen_models is not None,
            "frozen_model_provenance": frozen_provenance,
            "correctness_gate": "PASS" if not missing else "INCOMPLETE",
            "workload_identity_pinned": not missing,
            "calibration_and_holdout_disjoint": True,
            "hardware_event_intervals_summed": False,
            "hardware_observation_scope": (
                "routed nonoverlapping kernel events and explicitly overlapping "
                "reader/compute event envelopes"
            ),
            "threshold": component_threshold,
            "coverage": component_coverage,
            "threshold_checks": {
                "all_pass": component_pass,
                "groups": summaries,
            },
            "groups": summaries,
            "missing_cases": sorted(missing),
            "evidence": component_evidence,
        },
    )
    write_json(
        args.out_dir / "memory_ledger_validation.json",
        {
            "schema_version": 1,
            "gate_kind": "memory_ledger",
            "contract_id": contract["contract_id"],
            "contract_sha256": sha256_file(contract_path),
            "case_contract_sha256": sha256_file(cases_path),
            "status": ledger_status,
            "parameters_frozen": True,
            "correctness_gate": "PASS" if not missing else "INCOMPLETE",
            "workload_identity_pinned": not missing,
            "calibration_and_holdout_disjoint": True,
            "hardware_observation_scope": "routed hardware exposes timing and realized-work counters but not HBM byte counters; request/byte/FIFO conservation below is execution-driven simulator evidence",
            "coverage": ledger_coverage,
            "threshold_checks": {
                "all_pass": ledger_pass,
            },
            "missing_cases": sorted(missing),
            "rows": ledger_rows,
        },
    )
    write_json(
        args.out_dir / "structural_work_validation.json",
        {
            "schema_version": 1,
            "gate_kind": "structural_work",
            "contract_id": contract["contract_id"],
            "contract_sha256": sha256_file(contract_path),
            "case_contract_sha256": sha256_file(cases_path),
            "status": structural_status,
            "parameters_frozen": True,
            "correctness_gate": "PASS" if not missing else "INCOMPLETE",
            "workload_identity_pinned": not missing,
            "calibration_and_holdout_disjoint": True,
            "hardware_observation_scope": (
                "Spine iterations, range-task count, and processed-edge count from "
                "routed KERNEL_PAIR_RESULT records. G+R has no equivalent routed counter."
            ),
            "grasu_regraph_hardware_counter_limitation_explicit": True,
            "coverage": structural_coverage,
            "threshold_checks": {
                "all_pass": structural_pass,
            },
            "missing_cases": sorted(missing),
            "rows": structural_rows,
        },
    )
    print(
        f"CURRENT_FPGA_COMPONENT_{component_status} groups={len(summaries)}/{expected_component_groups} "
        f"CURRENT_FPGA_LEDGER_{ledger_status} rows={len(ledger_rows)} "
        f"CURRENT_FPGA_STRUCTURAL_{structural_status} rows={len(structural_rows)}/"
        f"{expected_structural_rows} missing={len(missing)}"
    )
    return 0 if (component_pass and ledger_pass and structural_pass) or args.allow_partial else 1


if __name__ == "__main__":
    raise SystemExit(main())
