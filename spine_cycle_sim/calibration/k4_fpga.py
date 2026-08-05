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
    fields: dict[str, str] = {}
    for token in lines[-1].split()[1:]:
        if "=" in token:
            key, value = token.split("=", 1)
            fields[key] = value
    if (
        fields.get("status") != "PASS"
        or fields.get("mismatches", fields.get("rank_mismatches")) != "0"
        or fields.get("conversion_cost") != "absent"
    ):
        raise ValueError(f"hardware protocol gate failed: {log}")
    return fields


def _read_simulation(path: Path, clock_mhz: float) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    result = payload.get("result", {})
    if (
        payload.get("status") != "PASS"
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

        simulation = _read_simulation(spec.simulation_manifest.resolve(), clock_mhz)
        sim_steps = int(simulation.get("supersteps", 0))
        hw_steps = {int(protocol["executed_supersteps"]) for protocol in protocols}
        partitions = {
            int(protocol["destination_partitions"]) for protocol in protocols
        }
        if hw_steps != {sim_steps}:
            raise ValueError(f"superstep mismatch for {spec.case}: {hw_steps} vs {sim_steps}")
        if len(partitions) != 1:
            raise ValueError(f"partition count changed across repeats: {spec.case}")

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
                algorithm=algorithms.pop(),
                graph=graphs.pop(),
                simulation_manifest=str(spec.simulation_manifest.resolve()),
                simulation_cycles=float(simulation["cycles"]),
                hardware_event_ms=median_ms,
                hardware_cycles=median_ms * clock_mhz * 1000.0,
                hardware_samples=len(event_samples),
                hardware_cv_pct=cv_pct,
                supersteps=sim_steps,
                destination_partitions=partitions.pop(),
            )
        )
    return records


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
