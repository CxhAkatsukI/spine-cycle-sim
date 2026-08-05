"""Calibration of K4-shared G+R simulator cycles to routed FPGA events.

The execution-driven simulator remains the structural timing model.  This
module fits one non-negative scale factor to correctness-admitted FPGA event
windows and keeps calibration and holdout cases strictly disjoint.  It does
not alter HBM timing, FIFO behavior, or the simulator's raw cycle count.
"""

from __future__ import annotations

import csv
from dataclasses import asdict, dataclass
import json
import math
from pathlib import Path
import statistics
from typing import Any, Iterable


@dataclass(frozen=True)
class K4CaseSpec:
    case: str
    role: str
    simulation_manifest: Path


@dataclass(frozen=True)
class K4MicrobenchSpec:
    case: str
    role: str
    simulation_manifest: Path
    hardware_run_dir: Path


@dataclass(frozen=True)
class K4TimingRecord:
    case: str
    role: str
    algorithm: str
    graph: str
    simulation_manifest: str
    simulation_cycles: float
    hardware_event_ms: float
    hardware_cycles: float
    hardware_samples: int
    hardware_cv_pct: float
    supersteps: int
    destination_partitions: int
    vertices: int = 0
    executed_pma_slots: int = 0


@dataclass(frozen=True)
class K4EventScaleModel:
    scale: float
    calibration_cases: tuple[str, ...]
    clock_mhz: float
    claim_class: str = "k4_fpga_event_envelope_calibrated"

    def predict(self, simulation_cycles: float) -> float:
        if not math.isfinite(simulation_cycles) or simulation_cycles < 0:
            raise ValueError("simulation cycles must be finite and non-negative")
        return self.scale * simulation_cycles


@dataclass(frozen=True)
class K4EventComponentModel:
    fixed_cycles: float
    vertex_cycles: float
    pma_slot_cycles: float
    calibration_cases: tuple[str, ...]
    clock_mhz: float
    claim_class: str = "k4_fpga_fullpr_component_envelope_calibrated"

    def predict(self, vertices: int, executed_pma_slots: int) -> float:
        if vertices <= 0 or executed_pma_slots <= 0:
            raise ValueError("component prediction requires positive realized work")
        return (
            self.fixed_cycles
            + self.vertex_cycles * vertices
            + self.pma_slot_cycles * executed_pma_slots
        )


def _parse_protocol_line(line: str) -> dict[str, str]:
    fields: dict[str, str] = {}
    for token in line.split()[1:]:
        if "=" in token:
            key, value = token.split("=", 1)
            fields[key] = value
    return fields


def _read_summary(path: Path) -> dict[str, dict[str, str]]:
    with path.open(encoding="utf-8", newline="") as source:
        rows = list(csv.DictReader(source, delimiter="\t"))
    result: dict[str, dict[str, str]] = {}
    for row in rows:
        case = row.get("case", "")
        if not case or case in result:
            raise ValueError(f"invalid or duplicate case in {path}: {case!r}")
        if (
            row.get("comparison_status") != "ADMITTED"
            or row.get("gr_status") != "PASS"
            or row.get("spine_status") != "PASS"
        ):
            raise ValueError(f"non-admitted hardware row in {path}: {case}")
        result[case] = row
    return result


def _read_hardware_protocol(summary: Path, case: str) -> dict[str, str]:
    log = summary.parent / case / "grasu_regraph" / "run.log"
    if not log.is_file():
        raise FileNotFoundError(f"missing G+R hardware log: {log}")
    lines = [
        line
        for line in log.read_text(encoding="utf-8").splitlines()
        if "_RESULT " in line
    ]
    if not lines:
        raise ValueError(f"missing G+R result line: {log}")
    fields = _parse_protocol_line(lines[-1])
    if (
        fields.get("status") != "PASS"
        or fields.get("mismatches", fields.get("rank_mismatches")) != "0"
        or fields.get("degree_mismatches", "0") != "0"
        or fields.get("shared_regraph_pipelines") != "1"
        or fields.get("conversion_cost") != "absent"
    ):
        raise ValueError(f"hardware protocol gate failed: {log}")
    return fields


def _read_simulation(path: Path, clock_mhz: float) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    result = payload.get("result")
    if not isinstance(result, dict) or not result:
        result_path = path.parent / "result.json"
        if not result_path.is_file():
            raise FileNotFoundError(
                f"simulation manifest has no embedded or sibling result: {path}"
            )
        result = json.loads(result_path.read_text(encoding="utf-8"))
    if (
        payload.get("status") != "PASS"
        or payload.get("admitted", True) is not True
        or result.get("success") is not True
        or result.get("correctness_mismatches") != 0
        or result.get("architecture_correctness_mismatches") != 0
        or result.get("mathematical_correctness_mismatches") != 0
        or result.get("conversion_cost_included") is not False
    ):
        raise ValueError(f"simulation protocol gate failed: {path}")
    if not math.isclose(float(result.get("core_mhz", 0.0)), clock_mhz):
        raise ValueError(f"simulation clock mismatch: {path}")
    return result


def _hardware_execution_rounds(
    algorithm: str, protocol: dict[str, str]
) -> int:
    if algorithm in {"weighted_sssp", "connected_components"}:
        key = "executed_supersteps"
    elif algorithm in {"full_pagerank", "residual_pagerank"}:
        key = "pipeline_executions"
    else:
        raise ValueError(f"unsupported K4 FPGA calibration algorithm: {algorithm}")
    rounds = int(protocol.get(key, 0))
    if rounds <= 0:
        raise ValueError(f"missing positive {key} in hardware protocol")
    if algorithm == "full_pagerank" and int(protocol.get("rounds", 0)) != rounds:
        raise ValueError("Full PageRank hardware rounds differ from pipeline executions")
    if algorithm == "residual_pagerank":
        propagation = int(protocol.get("propagation_rounds", -1))
        if propagation < 0 or rounds != propagation + 1:
            raise ValueError(
                "Residual PageRank hardware must contain one correction execution"
            )
    return rounds


def _simulation_execution_rounds(
    algorithm: str, simulation: dict[str, Any]
) -> int:
    key = "supersteps" if algorithm == "weighted_sssp" else "iterations"
    rounds = int(simulation.get(key, 0))
    if rounds <= 0:
        raise ValueError(f"missing positive simulator {key} for {algorithm}")
    return rounds


def load_k4_timing_records(
    summaries: Iterable[Path],
    case_specs: Iterable[K4CaseSpec],
    *,
    clock_mhz: float = 150.0,
) -> list[K4TimingRecord]:
    summary_paths = tuple(path.resolve() for path in summaries)
    specs = tuple(case_specs)
    if not summary_paths:
        raise ValueError("at least one hardware summary is required")
    if not specs:
        raise ValueError("at least one case specification is required")
    if len({spec.case for spec in specs}) != len(specs):
        raise ValueError("K4 case specifications contain duplicates")
    roles = {spec.role for spec in specs}
    if roles != {"calibration", "holdout"}:
        raise ValueError("K4 evidence requires calibration and holdout roles")

    repeats = [_read_summary(path) for path in summary_paths]
    records: list[K4TimingRecord] = []
    for spec in specs:
        rows = []
        protocols = []
        for path, repeat in zip(summary_paths, repeats):
            if spec.case not in repeat:
                raise ValueError(f"case {spec.case!r} is absent from {path}")
            rows.append(repeat[spec.case])
            protocols.append(_read_hardware_protocol(path, spec.case))
        algorithms = {row["algorithm"] for row in rows}
        graphs = {row["graph"] for row in rows}
        if len(algorithms) != 1 or len(graphs) != 1:
            raise ValueError(f"hardware repeat identity changed: {spec.case}")
        event_samples = [float(row["gr_event_e2e_ms"]) for row in rows]
        if any(not math.isfinite(value) or value <= 0 for value in event_samples):
            raise ValueError(f"invalid hardware event sample: {spec.case}")

        algorithm = next(iter(algorithms))
        simulation = _read_simulation(spec.simulation_manifest.resolve(), clock_mhz)
        sim_steps = _simulation_execution_rounds(algorithm, simulation)
        hw_steps = {
            _hardware_execution_rounds(algorithm, protocol)
            for protocol in protocols
        }
        partitions = {
            int(protocol["destination_partitions"]) for protocol in protocols
        }
        if hw_steps != {sim_steps}:
            raise ValueError(f"superstep mismatch for {spec.case}: {hw_steps} vs {sim_steps}")
        if len(partitions) != 1:
            raise ValueError(f"partition count changed across repeats: {spec.case}")

        vertices = int(simulation.get("vertices", 0))
        executed_pma_slots = int(simulation.get("compute_pma_slots", 0))
        if algorithm == "full_pagerank":
            if vertices <= 0 or executed_pma_slots <= 0:
                raise ValueError(f"missing FullPR realized work: {spec.case}")
            protocol_vertices = {int(protocol.get("vertices", 0)) for protocol in protocols}
            protocol_slots = {
                int(protocol.get("pma_slots_per_partition_pass", 0))
                * _hardware_execution_rounds(algorithm, protocol)
                for protocol in protocols
            }
            if protocol_vertices != {vertices} or protocol_slots != {executed_pma_slots}:
                raise ValueError(
                    f"FullPR realized work mismatch for {spec.case}: "
                    f"vertices={protocol_vertices} slots={protocol_slots}"
                )

        median_ms = statistics.median(event_samples)
        mean_ms = statistics.mean(event_samples)
        cv_pct = (
            100.0 * statistics.pstdev(event_samples) / mean_ms
            if len(event_samples) > 1
            else 0.0
        )
        records.append(
            K4TimingRecord(
                case=spec.case,
                role=spec.role,
                algorithm=algorithm,
                graph=graphs.pop(),
                simulation_manifest=str(spec.simulation_manifest.resolve()),
                simulation_cycles=float(simulation["cycles"]),
                hardware_event_ms=median_ms,
                hardware_cycles=median_ms * clock_mhz * 1000.0,
                hardware_samples=len(event_samples),
                hardware_cv_pct=cv_pct,
                supersteps=sim_steps,
                destination_partitions=partitions.pop(),
                vertices=vertices,
                executed_pma_slots=executed_pma_slots,
            )
        )
    return records


def load_k4_microbench_records(
    case_specs: Iterable[K4MicrobenchSpec],
    *,
    clock_mhz: float = 150.0,
) -> list[K4TimingRecord]:
    records: list[K4TimingRecord] = []
    for spec in case_specs:
        summary = spec.hardware_run_dir.resolve() / "summary.tsv"
        with summary.open(encoding="utf-8", newline="") as source:
            rows = list(csv.DictReader(source, delimiter="\t"))
        if len(rows) != 1 or rows[0].get("status") != "PASS":
            raise ValueError(f"microbenchmark hardware gate failed: {summary}")
        row = rows[0]
        if row.get("algorithm") != "full_pagerank":
            raise ValueError(f"microbenchmark is not FullPR: {summary}")
        protocol = _parse_protocol_line(row.get("result_line", ""))
        timing = _parse_protocol_line(row.get("timing_line", ""))
        if (
            protocol.get("status") != "PASS"
            or protocol.get("rank_mismatches") != "0"
            or protocol.get("degree_mismatches") != "0"
            or protocol.get("shared_regraph_pipelines") != "1"
            or protocol.get("conversion_cost") != "absent"
        ):
            raise ValueError(f"microbenchmark hardware protocol failed: {summary}")

        simulation_path = spec.simulation_manifest.resolve()
        simulation = _read_simulation(simulation_path, clock_mhz)
        rounds = _simulation_execution_rounds("full_pagerank", simulation)
        hardware_rounds = _hardware_execution_rounds("full_pagerank", protocol)
        vertices = int(simulation.get("vertices", 0))
        hardware_vertices = int(protocol.get("vertices", 0))
        executed_pma_slots = int(simulation.get("compute_pma_slots", 0))
        hardware_pma_slots = (
            int(protocol.get("pma_slots_per_partition_pass", 0)) * hardware_rounds
        )
        partitions = int(protocol.get("destination_partitions", 0))
        simulation_partitions = int(simulation.get("destination_partitions", 0))
        if (
            rounds != hardware_rounds
            or vertices <= 0
            or vertices != hardware_vertices
            or executed_pma_slots <= 0
            or executed_pma_slots != hardware_pma_slots
            or partitions <= 0
            or partitions != simulation_partitions
        ):
            raise ValueError(f"microbenchmark realized work mismatch: {spec.case}")
        event_ms = float(timing.get("device_e2e_ms", 0.0))
        if not math.isfinite(event_ms) or event_ms <= 0:
            raise ValueError(f"invalid microbenchmark event time: {summary}")
        records.append(
            K4TimingRecord(
                case=spec.case,
                role=spec.role,
                algorithm="full_pagerank",
                graph=str(spec.hardware_run_dir.resolve()),
                simulation_manifest=str(simulation_path),
                simulation_cycles=float(simulation["cycles"]),
                hardware_event_ms=event_ms,
                hardware_cycles=event_ms * clock_mhz * 1000.0,
                hardware_samples=1,
                hardware_cv_pct=0.0,
                supersteps=rounds,
                destination_partitions=partitions,
                vertices=vertices,
                executed_pma_slots=executed_pma_slots,
            )
        )
    return records


def _solve_three_by_three(matrix: list[list[float]], vector: list[float]) -> list[float]:
    augmented = [row[:] + [value] for row, value in zip(matrix, vector)]
    for column in range(3):
        pivot = max(range(column, 3), key=lambda row: abs(augmented[row][column]))
        if abs(augmented[pivot][column]) < 1.0e-12:
            raise ValueError("component calibration features are rank deficient")
        augmented[column], augmented[pivot] = augmented[pivot], augmented[column]
        divisor = augmented[column][column]
        augmented[column] = [value / divisor for value in augmented[column]]
        for row in range(3):
            if row == column:
                continue
            factor = augmented[row][column]
            augmented[row] = [
                value - factor * pivot_value
                for value, pivot_value in zip(augmented[row], augmented[column])
            ]
    return [augmented[row][3] for row in range(3)]


def fit_k4_fullpr_component_model(
    records: Iterable[K4TimingRecord],
) -> K4EventComponentModel:
    rows = tuple(records)
    calibration = [row for row in rows if row.role == "calibration"]
    holdout = [row for row in rows if row.role == "holdout"]
    if len(calibration) < 3 or not holdout:
        raise ValueError("component fit requires at least three calibration rows and a holdout")
    if {row.case for row in calibration} & {row.case for row in holdout}:
        raise ValueError("K4 calibration and holdout cases overlap")
    if any(
        row.algorithm != "full_pagerank"
        or row.vertices <= 0
        or row.executed_pma_slots <= 0
        or row.hardware_cycles <= 0
        for row in rows
    ):
        raise ValueError("component fit requires positive FullPR realized work")

    vertex_scale = max(row.vertices for row in calibration)
    slot_scale = max(row.executed_pma_slots for row in calibration)
    features = [
        [1.0, row.vertices / vertex_scale, row.executed_pma_slots / slot_scale]
        for row in calibration
    ]
    matrix = [
        [sum(feature[i] * feature[j] for feature in features) for j in range(3)]
        for i in range(3)
    ]
    vector = [
        sum(feature[i] * row.hardware_cycles for feature, row in zip(features, calibration))
        for i in range(3)
    ]
    fixed, scaled_vertex, scaled_slot = _solve_three_by_three(matrix, vector)
    coefficients = (fixed, scaled_vertex / vertex_scale, scaled_slot / slot_scale)
    if any(not math.isfinite(value) or value < 0 for value in coefficients):
        raise ValueError("component fit produced a negative or non-finite coefficient")
    clocks = [
        row.hardware_cycles / (row.hardware_event_ms * 1000.0) for row in rows
    ]
    if any(not math.isclose(clock, clocks[0], rel_tol=1.0e-12) for clock in clocks):
        raise ValueError("K4 records use different hardware clocks")
    return K4EventComponentModel(
        fixed_cycles=coefficients[0],
        vertex_cycles=coefficients[1],
        pma_slot_cycles=coefficients[2],
        calibration_cases=tuple(sorted(row.case for row in calibration)),
        clock_mhz=clocks[0],
    )


def fit_k4_event_scale(records: Iterable[K4TimingRecord]) -> K4EventScaleModel:
    rows = tuple(records)
    calibration = [row for row in rows if row.role == "calibration"]
    holdout = [row for row in rows if row.role == "holdout"]
    if not calibration or not holdout:
        raise ValueError("K4 fit requires disjoint calibration and holdout rows")
    if {row.case for row in calibration} & {row.case for row in holdout}:
        raise ValueError("K4 calibration and holdout cases overlap")
    if any(row.simulation_cycles <= 0 or row.hardware_cycles <= 0 for row in calibration):
        raise ValueError("K4 calibration has no positive simulated work")
    # A single multiplicative envelope is fitted in log space so each graph
    # scale has equal relative weight.  This avoids letting the largest cycle
    # count dominate a model whose acceptance metric is percentage error.
    scale = math.exp(
        statistics.mean(
            math.log(row.hardware_cycles / row.simulation_cycles)
            for row in calibration
        )
    )
    if not math.isfinite(scale) or scale < 0:
        raise ValueError("K4 event scale is invalid")
    clocks = [
        row.hardware_cycles / (row.hardware_event_ms * 1000.0) for row in rows
    ]
    if any(not math.isclose(clock, clocks[0], rel_tol=1.0e-12) for clock in clocks):
        raise ValueError("K4 records use different hardware clocks")
    return K4EventScaleModel(
        scale=scale,
        calibration_cases=tuple(sorted(row.case for row in calibration)),
        clock_mhz=clocks[0],
    )


def k4_prediction_rows(
    records: Iterable[K4TimingRecord], model: K4EventScaleModel
) -> list[dict[str, Any]]:
    result = []
    for record in records:
        predicted = model.predict(record.simulation_cycles)
        raw_error = 100.0 * (
            record.simulation_cycles - record.hardware_cycles
        ) / record.hardware_cycles
        calibrated_error = 100.0 * (
            predicted - record.hardware_cycles
        ) / record.hardware_cycles
        result.append(
            {
                **asdict(record),
                "calibrated_cycles": predicted,
                "raw_signed_error_pct": raw_error,
                "raw_absolute_error_pct": abs(raw_error),
                "calibrated_signed_error_pct": calibrated_error,
                "calibrated_absolute_error_pct": abs(calibrated_error),
            }
        )
    return result


def k4_component_prediction_rows(
    records: Iterable[K4TimingRecord], model: K4EventComponentModel
) -> list[dict[str, Any]]:
    result = []
    for record in records:
        predicted = model.predict(record.vertices, record.executed_pma_slots)
        raw_error = 100.0 * (
            record.simulation_cycles - record.hardware_cycles
        ) / record.hardware_cycles
        calibrated_error = 100.0 * (
            predicted - record.hardware_cycles
        ) / record.hardware_cycles
        result.append(
            {
                **asdict(record),
                "calibrated_cycles": predicted,
                "raw_signed_error_pct": raw_error,
                "raw_absolute_error_pct": abs(raw_error),
                "calibrated_signed_error_pct": calibrated_error,
                "calibrated_absolute_error_pct": abs(calibrated_error),
            }
        )
    return result


def k4_group_summary(rows: Iterable[dict[str, Any]]) -> list[dict[str, Any]]:
    materialized = list(rows)
    result = []
    for role in ("calibration", "holdout", "all"):
        selected = materialized if role == "all" else [row for row in materialized if row["role"] == role]
        if not selected:
            continue
        raw = [float(row["raw_absolute_error_pct"]) for row in selected]
        calibrated = [
            float(row["calibrated_absolute_error_pct"]) for row in selected
        ]
        result.append(
            {
                "role": role,
                "cases": len(selected),
                "raw_median_absolute_error_pct": statistics.median(raw),
                "raw_max_absolute_error_pct": max(raw),
                "calibrated_median_absolute_error_pct": statistics.median(calibrated),
                "calibrated_max_absolute_error_pct": max(calibrated),
            }
        )
    return result
