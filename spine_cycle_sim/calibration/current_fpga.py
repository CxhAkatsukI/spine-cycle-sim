"""Calibration helpers for the current Spine and sharded-K4 FPGA systems.

The simulator remains the execution model.  Calibration applies one positive
scale per architecture/algorithm (or per observable component) and never uses
holdout rows when fitting that scale.
"""

from __future__ import annotations

from dataclasses import dataclass
import math
import statistics
from typing import Iterable


@dataclass(frozen=True)
class CurrentFPGATimingRecord:
    architecture: str
    algorithm: str
    profile_id: str
    dataset: str
    role: str
    simulator_cycles: float
    hardware_cycles: float


@dataclass(frozen=True)
class CurrentFPGAComponentRecord:
    architecture: str
    algorithm: str
    profile_id: str
    dataset: str
    role: str
    component: str
    simulator_cycles: float
    hardware_cycles: float
    hardware_observation: str


@dataclass(frozen=True)
class PositiveScaleModel:
    architecture: str
    algorithm: str
    component: str | None
    scale: float
    calibration_datasets: tuple[str, ...]

    def predict(self, simulator_cycles: float) -> float:
        _require_positive_finite(simulator_cycles, "simulator_cycles")
        return self.scale * simulator_cycles


def _require_positive_finite(value: float, name: str) -> None:
    if not math.isfinite(value) or value <= 0:
        raise ValueError(f"{name} must be finite and positive")


def _validate_role(role: str) -> None:
    if role not in {"calibration", "holdout"}:
        raise ValueError(f"invalid evidence role: {role!r}")


def _geometric_mean(values: Iterable[float]) -> float:
    materialized = tuple(values)
    if not materialized:
        raise ValueError("geometric mean requires at least one value")
    for value in materialized:
        _require_positive_finite(value, "geometric-mean input")
    return math.exp(statistics.fmean(math.log(value) for value in materialized))


def fit_total_scale(records: Iterable[CurrentFPGATimingRecord]) -> PositiveScaleModel:
    rows = tuple(records)
    if not rows:
        raise ValueError("total-cycle calibration requires records")
    identities = {(row.architecture, row.algorithm, row.profile_id) for row in rows}
    if len(identities) != 1:
        raise ValueError("total-cycle fit must contain one architecture/algorithm/profile")
    for row in rows:
        _validate_role(row.role)
        _require_positive_finite(row.simulator_cycles, "simulator_cycles")
        _require_positive_finite(row.hardware_cycles, "hardware_cycles")
    calibration = tuple(row for row in rows if row.role == "calibration")
    holdout = tuple(row for row in rows if row.role == "holdout")
    if len(calibration) < 2 or len(holdout) < 1:
        raise ValueError("total-cycle fit requires at least two calibration and one holdout rows")
    if {row.dataset for row in calibration} & {row.dataset for row in holdout}:
        raise ValueError("calibration and holdout datasets overlap")
    architecture, algorithm, _profile_id = next(iter(identities))
    return PositiveScaleModel(
        architecture=architecture,
        algorithm=algorithm,
        component=None,
        scale=_geometric_mean(
            row.hardware_cycles / row.simulator_cycles for row in calibration
        ),
        calibration_datasets=tuple(sorted(row.dataset for row in calibration)),
    )


def fit_component_scale(
    records: Iterable[CurrentFPGAComponentRecord],
) -> PositiveScaleModel:
    rows = tuple(records)
    if not rows:
        raise ValueError("component calibration requires records")
    identities = {
        (row.architecture, row.algorithm, row.profile_id, row.component)
        for row in rows
    }
    if len(identities) != 1:
        raise ValueError("component fit must contain one architecture/algorithm/profile/component")
    observations = {row.hardware_observation for row in rows}
    if len(observations) != 1 or not next(iter(observations)):
        raise ValueError("hardware component observation scope must be explicit and stable")
    for row in rows:
        _validate_role(row.role)
        _require_positive_finite(row.simulator_cycles, "simulator_cycles")
        _require_positive_finite(row.hardware_cycles, "hardware_cycles")
    calibration = tuple(row for row in rows if row.role == "calibration")
    holdout = tuple(row for row in rows if row.role == "holdout")
    if len(calibration) < 2 or len(holdout) < 1:
        raise ValueError("component fit requires at least two calibration and one holdout rows")
    if {row.dataset for row in calibration} & {row.dataset for row in holdout}:
        raise ValueError("calibration and holdout datasets overlap")
    architecture, algorithm, _profile_id, component = next(iter(identities))
    return PositiveScaleModel(
        architecture=architecture,
        algorithm=algorithm,
        component=component,
        scale=_geometric_mean(
            row.hardware_cycles / row.simulator_cycles for row in calibration
        ),
        calibration_datasets=tuple(sorted(row.dataset for row in calibration)),
    )


def absolute_error_percent(predicted: float, observed: float) -> float:
    _require_positive_finite(predicted, "predicted")
    _require_positive_finite(observed, "observed")
    return 100.0 * abs(predicted - observed) / observed


def _average_ranks(values: list[float]) -> list[float]:
    order = sorted(range(len(values)), key=values.__getitem__)
    ranks = [0.0] * len(values)
    index = 0
    while index < len(order):
        end = index + 1
        while end < len(order) and values[order[end]] == values[order[index]]:
            end += 1
        rank = 0.5 * (index + end - 1) + 1.0
        for position in order[index:end]:
            ranks[position] = rank
        index = end
    return ranks


def spearman_rank_correlation(left: Iterable[float], right: Iterable[float]) -> float:
    left_values = list(left)
    right_values = list(right)
    if len(left_values) != len(right_values) or len(left_values) < 2:
        raise ValueError("Spearman correlation requires equal vectors with at least two rows")
    left_ranks = _average_ranks(left_values)
    right_ranks = _average_ranks(right_values)
    left_mean = statistics.fmean(left_ranks)
    right_mean = statistics.fmean(right_ranks)
    numerator = sum(
        (a - left_mean) * (b - right_mean)
        for a, b in zip(left_ranks, right_ranks)
    )
    left_norm = math.sqrt(sum((value - left_mean) ** 2 for value in left_ranks))
    right_norm = math.sqrt(sum((value - right_mean) ** 2 for value in right_ranks))
    if left_norm == 0 or right_norm == 0:
        raise ValueError("Spearman correlation is undefined for a constant vector")
    return numerator / (left_norm * right_norm)


def total_prediction_rows(
    records: Iterable[CurrentFPGATimingRecord], model: PositiveScaleModel
) -> list[dict[str, object]]:
    rows: list[dict[str, object]] = []
    for record in records:
        if (record.architecture, record.algorithm) != (
            model.architecture,
            model.algorithm,
        ):
            raise ValueError("total-cycle model identity does not match record")
        prediction = model.predict(record.simulator_cycles)
        rows.append(
            {
                "architecture": record.architecture,
                "algorithm": record.algorithm,
                "profile_id": record.profile_id,
                "dataset": record.dataset,
                "role": record.role,
                "simulator_cycles": record.simulator_cycles,
                "hardware_cycles": record.hardware_cycles,
                "scale": model.scale,
                "predicted_cycles": prediction,
                "absolute_error_percent": absolute_error_percent(
                    prediction, record.hardware_cycles
                ),
            }
        )
    return rows


def component_prediction_rows(
    records: Iterable[CurrentFPGAComponentRecord], model: PositiveScaleModel
) -> list[dict[str, object]]:
    rows: list[dict[str, object]] = []
    for record in records:
        if (record.architecture, record.algorithm, record.component) != (
            model.architecture,
            model.algorithm,
            model.component,
        ):
            raise ValueError("component model identity does not match record")
        prediction = model.predict(record.simulator_cycles)
        rows.append(
            {
                "architecture": record.architecture,
                "algorithm": record.algorithm,
                "profile_id": record.profile_id,
                "dataset": record.dataset,
                "role": record.role,
                "component": record.component,
                "hardware_observation": record.hardware_observation,
                "simulator_cycles": record.simulator_cycles,
                "hardware_cycles": record.hardware_cycles,
                "scale": model.scale,
                "predicted_cycles": prediction,
                "absolute_error_percent": absolute_error_percent(
                    prediction, record.hardware_cycles
                ),
            }
        )
    return rows

