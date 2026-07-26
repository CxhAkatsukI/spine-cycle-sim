"""Calibration layer for source-matched candidate-10 maintenance runs."""

from __future__ import annotations

import csv
from dataclasses import asdict, dataclass
import json
import math
from pathlib import Path
import statistics
from typing import Any, Iterable

from .maintenance import _solve_linear


@dataclass(frozen=True)
class Candidate10TimingRecord:
    case_id: str
    evidence_case: str
    role: str
    input_edges: int
    classify_blocks: int
    unique_sources: int
    simulated_cycles: float
    hardware_cycles: float


@dataclass(frozen=True)
class Candidate10ResidualModel:
    fixed_cycles: float
    per_unique_source_cycles: float
    per_extra_edge_cycles: float
    per_classify_block_cycles: float
    max_calibration_unique_sources: int
    max_calibration_extra_edges: int
    max_calibration_classify_blocks: int
    frequency_mhz: float = 150.0

    def correction(
        self, record: Candidate10TimingRecord, *, bounded: bool = True
    ) -> float:
        extra_edges = max(0, record.input_edges - record.unique_sources)
        unique_sources = record.unique_sources
        classify_blocks = record.classify_blocks
        if bounded:
            unique_sources = min(
                unique_sources, self.max_calibration_unique_sources
            )
            extra_edges = min(extra_edges, self.max_calibration_extra_edges)
            classify_blocks = min(
                classify_blocks, self.max_calibration_classify_blocks
            )
        return (
            self.fixed_cycles
            + self.per_unique_source_cycles * unique_sources
            + self.per_extra_edge_cycles * extra_edges
            + self.per_classify_block_cycles * classify_blocks
        )

    def within_calibration_domain(self, record: Candidate10TimingRecord) -> bool:
        return (
            record.unique_sources <= self.max_calibration_unique_sources
            and max(0, record.input_edges - record.unique_sources)
            <= self.max_calibration_extra_edges
            and record.classify_blocks <= self.max_calibration_classify_blocks
        )

    def predict(self, record: Candidate10TimingRecord) -> float:
        return max(0.0, record.simulated_cycles + self.correction(record))

    def as_dict(self) -> dict[str, float | int]:
        return asdict(self)


def read_candidate10_matrix(path: Path) -> list[Candidate10TimingRecord]:
    with path.open("r", encoding="utf-8", newline="") as stream:
        rows = list(csv.DictReader(stream))
    records = [
        Candidate10TimingRecord(
            case_id=row["case_id"],
            evidence_case=row["evidence_case"],
            role=row["role"],
            input_edges=int(row["input_edges"]),
            classify_blocks=int(row["classify_blocks"]),
            unique_sources=int(row["unique_sources"]),
            simulated_cycles=float(row["simulated_cycles"]),
            hardware_cycles=float(row["hardware_cycles"]),
        )
        for row in rows
        if row.get("status") == "PASS"
    ]
    if len(records) != len(rows):
        raise ValueError("candidate-10 matrix contains missing or failed rows")
    return records


def fit_candidate10_residual(
    records: Iterable[Candidate10TimingRecord],
) -> Candidate10ResidualModel:
    calibration = [record for record in records if record.role == "calibration"]
    if len(calibration) < 5:
        raise ValueError("candidate-10 residual fit requires five calibration rows")
    if not any(record.input_edges == 0 for record in calibration):
        raise ValueError("candidate-10 calibration requires a zero-edge fixed anchor")
    if not any(record.input_edges > record.unique_sources for record in calibration):
        raise ValueError(
            "candidate-10 calibration requires an extra-edge anchor"
        )
    for record in calibration:
        if (
            record.input_edges < 0
            or record.unique_sources < 0
            or record.unique_sources > record.input_edges
            or record.classify_blocks < 0
        ):
            raise ValueError(f"invalid candidate-10 features: {record.case_id}")
    zero_anchors = [
        record.hardware_cycles - record.simulated_cycles
        for record in calibration
        if record.input_edges == 0
    ]
    fixed = statistics.mean(zero_anchors)
    nonzero = [record for record in calibration if record.input_edges > 0]
    design = [
        [
            float(record.unique_sources),
            float(record.input_edges - record.unique_sources),
            float(record.classify_blocks),
        ]
        for record in nonzero
    ]
    residual = [
        record.hardware_cycles - record.simulated_cycles - fixed
        for record in nonzero
    ]
    per_source, per_extra_edge, per_block = _fit_nonnegative_ols(
        design, residual
    )
    return Candidate10ResidualModel(
        fixed,
        per_source,
        per_extra_edge,
        per_block,
        max(record.unique_sources for record in calibration),
        max(record.input_edges - record.unique_sources for record in calibration),
        max(record.classify_blocks for record in calibration),
    )


def _fit_nonnegative_ols(
    design: list[list[float]], values: list[float]
) -> tuple[float, float, float]:
    """Solve the three-term NNLS problem by enumerating active sets."""

    dimensions = 3
    best = [0.0] * dimensions
    best_error = sum(value * value for value in values)
    for mask in range(1, 1 << dimensions):
        active = [index for index in range(dimensions) if mask & (1 << index)]
        scales = [
            math.sqrt(sum(row[index] * row[index] for row in design))
            for index in active
        ]
        if any(scale == 0.0 for scale in scales):
            continue
        normalized = [
            [row[index] / scale for index, scale in zip(active, scales)]
            for row in design
        ]
        size = len(active)
        xtx = [
            [
                sum(row[left] * row[right] for row in normalized)
                for right in range(size)
            ]
            for left in range(size)
        ]
        if not _is_full_rank(xtx):
            continue
        xty = [
            sum(row[column] * value for row, value in zip(normalized, values))
            for column in range(size)
        ]
        scaled_coefficients = _solve_linear(xtx, xty)
        coefficients = [0.0] * dimensions
        valid = True
        for index, scale, coefficient in zip(
            active, scales, scaled_coefficients
        ):
            unscaled = coefficient / scale
            if unscaled < -1.0e-9:
                valid = False
                break
            coefficients[index] = max(0.0, unscaled)
        if not valid:
            continue
        error = sum(
            (
                value
                - sum(coefficient * feature for coefficient, feature in zip(coefficients, row))
            )
            ** 2
            for row, value in zip(design, values)
        )
        if error < best_error:
            best_error = error
            best = coefficients
    return best[0], best[1], best[2]


def _is_full_rank(matrix: list[list[float]]) -> bool:
    work = [row[:] for row in matrix]
    size = len(work)
    for column in range(size):
        pivot = max(range(column, size), key=lambda row: abs(work[row][column]))
        if abs(work[pivot][column]) < 1.0e-10:
            return False
        work[column], work[pivot] = work[pivot], work[column]
        for row in range(column + 1, size):
            factor = work[row][column] / work[column][column]
            for item in range(column, size):
                work[row][item] -= factor * work[column][item]
    return True


def candidate10_prediction_rows(
    records: Iterable[Candidate10TimingRecord],
    model: Candidate10ResidualModel,
) -> list[dict[str, Any]]:
    rows = []
    for record in records:
        predicted = model.predict(record)
        error_pct = (
            100.0 * (predicted - record.hardware_cycles) / record.hardware_cycles
            if record.hardware_cycles
            else 0.0
        )
        rows.append(
            {
                **asdict(record),
                "extra_edges": max(
                    0, record.input_edges - record.unique_sources
                ),
                "within_calibration_domain": model.within_calibration_domain(record),
                "residual_correction_cycles": model.correction(record),
                "raw_extrapolated_residual_cycles": model.correction(
                    record, bounded=False
                ),
                "predicted_cycles": predicted,
                "error_pct": error_pct,
                "abs_error_pct": abs(error_pct),
            }
        )
    return rows


def summarize_candidate10_predictions(
    rows: Iterable[dict[str, Any]],
) -> list[dict[str, Any]]:
    grouped: dict[str, list[float]] = {}
    for row in rows:
        grouped.setdefault(str(row["role"]), []).append(
            float(row["abs_error_pct"])
        )
    return [
        {
            "role": role,
            "cases": len(errors),
            "median_abs_error_pct": statistics.median(errors),
            "max_abs_error_pct": max(errors),
        }
        for role, errors in sorted(grouped.items())
    ]


def write_candidate10_analysis(
    matrix_path: Path,
    out_dir: Path,
) -> dict[str, Any]:
    records = read_candidate10_matrix(matrix_path)
    model = fit_candidate10_residual(records)
    predictions = candidate10_prediction_rows(records, model)
    summary = summarize_candidate10_predictions(predictions)
    out_dir.mkdir(parents=True, exist_ok=True)
    _write_csv(out_dir / "predictions.csv", predictions)
    _write_csv(out_dir / "group_summary.csv", summary)
    payload = {
        "schema_version": 3,
        "claim": "candidate10_bounded_diagnostic_residual_layer",
        "model": model.as_dict(),
        "matrix": str(matrix_path.resolve()),
        "calibration_cases": [
            record.case_id for record in records if record.role == "calibration"
        ],
        "holdout_cases": [
            record.case_id for record in records if record.role == "holdout"
        ],
        "summary": summary,
        "limitations": [
            "The bounded correction diagnoses HLS/event-window work still missing from the structural core; it is not part of the execution-driven simulator and does not replace HBM timing.",
            "Only calibration rows fit coefficients; holdout rows remain disjoint.",
            "Feature values beyond the calibration maxima are clamped. Raw extrapolated residuals are exported for audit only and must not be used as predictions.",
            "The per-extra-edge coefficient is a composite of unresolved writer/AXI behavior in the calibration cases, not a mechanism that is claimed to generalize.",
            "The 65K task-capacity stress row does not fit coefficients and remains an out-of-domain structural diagnostic.",
            "Workload roles are frozen-analysis roles, not a claim that timing evidence was hidden during model development; a new hardware run is required for a pristine blind holdout.",
            "The frozen hardware evidence contains one measured timing sample per microbenchmark, so jitter is not estimable.",
        ],
    }
    (out_dir / "model.json").write_text(
        json.dumps(payload, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return payload


def _write_csv(path: Path, rows: Iterable[dict[str, Any]]) -> None:
    materialized = list(rows)
    if not materialized:
        raise ValueError(f"refusing to write empty CSV: {path}")
    fields = list(materialized[0])
    with path.open("w", encoding="utf-8", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=fields, lineterminator="\n")
        writer.writeheader()
        writer.writerows(materialized)
