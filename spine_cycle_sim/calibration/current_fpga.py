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


@dataclass(frozen=True)
class CurrentFPGAComposedRecord:
    """One structurally admitted simulator/FPGA timing pair.

    ``hardware_iterative_cycles`` is the routed reader/compute kernel span.  It
    already contains overlap and therefore must not be reconstructed by adding
    the individual reader and compute event intervals.
    """

    architecture: str
    algorithm: str
    profile_id: str
    dataset: str
    role: str
    simulator_maintenance_cycles: float
    simulator_iterative_cycles: float
    iterations: int
    hardware_maintenance_cycles: float
    hardware_iterative_cycles: float


@dataclass(frozen=True)
class ComposedTimingModel:
    """HLS-structured timing model for the current routed Spine design."""

    architecture: str
    algorithm: str
    maintenance_scale: float
    iterative_fixed_cycles_per_iteration: float
    iterative_simulator_scale: float
    calibration_datasets: tuple[str, ...]

    def predict_components(
        self,
        simulator_maintenance_cycles: float,
        simulator_iterative_cycles: float,
        iterations: int,
    ) -> dict[str, float]:
        _require_positive_finite(
            simulator_maintenance_cycles, "simulator_maintenance_cycles"
        )
        if not math.isfinite(simulator_iterative_cycles) or simulator_iterative_cycles < 0:
            raise ValueError("simulator_iterative_cycles must be finite and non-negative")
        if iterations < 0:
            raise ValueError("iterations must be non-negative")
        if iterations == 0 and simulator_iterative_cycles != 0:
            raise ValueError("zero-iteration rows cannot contain iterative simulator cycles")
        maintenance = self.maintenance_scale * simulator_maintenance_cycles
        iterative = (
            self.iterative_fixed_cycles_per_iteration * iterations
            + self.iterative_simulator_scale * simulator_iterative_cycles
        )
        return {
            "maintenance_cycles": maintenance,
            "iterative_cycles": iterative,
            "total_cycles": maintenance + iterative,
        }


def _require_positive_finite(value: float, name: str) -> None:
    if not math.isfinite(value) or value <= 0:
        raise ValueError(f"{name} must be finite and positive")


def _validate_role(role: str) -> None:
    if role not in {"calibration", "holdout"}:
        raise ValueError(f"invalid evidence role: {role!r}")


def _validate_composed_role(role: str) -> None:
    if role not in {"calibration", "development_validation", "holdout"}:
        raise ValueError(f"invalid composed-model evidence role: {role!r}")


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


def _fit_nonnegative_two_feature_model(
    features: list[tuple[float, float]], targets: list[float]
) -> tuple[float, float]:
    """Solve a two-column non-negative least-squares problem without SciPy."""

    if len(features) != len(targets) or len(features) < 2:
        raise ValueError("two-feature fit requires at least two aligned rows")
    x_scale = max(row[0] for row in features)
    y_scale = max(row[1] for row in features)
    if x_scale <= 0 or y_scale <= 0:
        raise ValueError("two-feature fit requires positive variation in both features")
    normalized = [(x / x_scale, y / y_scale) for x, y in features]
    xx = sum(x * x for x, _ in normalized)
    xy = sum(x * y for x, y in normalized)
    yy = sum(y * y for _, y in normalized)
    xt = sum(x * target for (x, _), target in zip(normalized, targets))
    yt = sum(y * target for (_, y), target in zip(normalized, targets))
    determinant = xx * yy - xy * xy
    if determinant <= 1e-12 * max(1.0, xx * yy):
        raise ValueError("composed timing calibration features are rank deficient")

    candidates: list[tuple[float, float]] = []
    unrestricted = (
        (xt * yy - yt * xy) / determinant,
        (yt * xx - xt * xy) / determinant,
    )
    if unrestricted[0] >= 0 and unrestricted[1] >= 0:
        candidates.append(unrestricted)
    candidates.extend(
        [
            (max(0.0, xt / xx), 0.0),
            (0.0, max(0.0, yt / yy)),
            (0.0, 0.0),
        ]
    )

    def squared_error(coefficients: tuple[float, float]) -> float:
        left, right = coefficients
        return sum(
            (left * x + right * y - target) ** 2
            for (x, y), target in zip(normalized, targets)
        )

    normalized_left, normalized_right = min(candidates, key=squared_error)
    return normalized_left / x_scale, normalized_right / y_scale


def fit_composed_timing_model(
    records: Iterable[CurrentFPGAComposedRecord],
) -> ComposedTimingModel:
    """Fit maintenance and iterative timing using calibration rows only.

    The iterative model has two physically interpretable terms: one fixed cost
    per HLS reader/compute launch and one scale on the execution-driven
    simulator span.  Zero-propagation rows train only the maintenance model.
    """

    rows = tuple(records)
    if not rows:
        raise ValueError("composed timing calibration requires records")
    identities = {(row.architecture, row.algorithm, row.profile_id) for row in rows}
    if len(identities) != 1:
        raise ValueError("composed fit must contain one architecture/algorithm/profile")
    for row in rows:
        _validate_composed_role(row.role)
        _require_positive_finite(
            row.simulator_maintenance_cycles, "simulator_maintenance_cycles"
        )
        _require_positive_finite(
            row.hardware_maintenance_cycles, "hardware_maintenance_cycles"
        )
        if row.iterations < 0:
            raise ValueError("iterations must be non-negative")
        for value, name in (
            (row.simulator_iterative_cycles, "simulator_iterative_cycles"),
            (row.hardware_iterative_cycles, "hardware_iterative_cycles"),
        ):
            if not math.isfinite(value) or value < 0:
                raise ValueError(f"{name} must be finite and non-negative")
        if row.iterations == 0 and (
            row.simulator_iterative_cycles != 0 or row.hardware_iterative_cycles != 0
        ):
            raise ValueError("zero-iteration rows cannot contain iterative cycles")

    calibration = tuple(row for row in rows if row.role == "calibration")
    non_calibration = tuple(row for row in rows if row.role != "calibration")
    if len(calibration) < 3:
        raise ValueError("composed fit requires at least three calibration rows")
    if {row.dataset for row in calibration} & {
        row.dataset for row in non_calibration
    }:
        raise ValueError("calibration and validation datasets overlap")
    iterative_calibration = tuple(row for row in calibration if row.iterations > 0)
    if len(iterative_calibration) < 2:
        raise ValueError("composed fit requires two propagating calibration rows")

    maintenance_scale = _geometric_mean(
        row.hardware_maintenance_cycles / row.simulator_maintenance_cycles
        for row in calibration
    )
    fixed, simulator_scale = _fit_nonnegative_two_feature_model(
        [
            (float(row.iterations), row.simulator_iterative_cycles)
            for row in iterative_calibration
        ],
        [row.hardware_iterative_cycles for row in iterative_calibration],
    )
    architecture, algorithm, _profile_id = next(iter(identities))
    return ComposedTimingModel(
        architecture=architecture,
        algorithm=algorithm,
        maintenance_scale=maintenance_scale,
        iterative_fixed_cycles_per_iteration=fixed,
        iterative_simulator_scale=simulator_scale,
        calibration_datasets=tuple(sorted(row.dataset for row in calibration)),
    )


def composed_prediction_rows(
    records: Iterable[CurrentFPGAComposedRecord], model: ComposedTimingModel
) -> list[dict[str, object]]:
    rows: list[dict[str, object]] = []
    for record in records:
        if (record.architecture, record.algorithm) != (
            model.architecture,
            model.algorithm,
        ):
            raise ValueError("composed timing model identity does not match record")
        prediction = model.predict_components(
            record.simulator_maintenance_cycles,
            record.simulator_iterative_cycles,
            record.iterations,
        )
        hardware_total = (
            record.hardware_maintenance_cycles + record.hardware_iterative_cycles
        )
        rows.append(
            {
                "architecture": record.architecture,
                "algorithm": record.algorithm,
                "profile_id": record.profile_id,
                "dataset": record.dataset,
                "role": record.role,
                "iterations": record.iterations,
                "simulator_maintenance_cycles": record.simulator_maintenance_cycles,
                "simulator_iterative_cycles": record.simulator_iterative_cycles,
                "hardware_maintenance_cycles": record.hardware_maintenance_cycles,
                "hardware_iterative_cycles": record.hardware_iterative_cycles,
                "hardware_total_cycles": hardware_total,
                "predicted_maintenance_cycles": prediction["maintenance_cycles"],
                "predicted_iterative_cycles": prediction["iterative_cycles"],
                "predicted_total_cycles": prediction["total_cycles"],
                "maintenance_absolute_error_percent": absolute_error_percent(
                    prediction["maintenance_cycles"],
                    record.hardware_maintenance_cycles,
                ),
                "iterative_absolute_error_percent": (
                    absolute_error_percent(
                        prediction["iterative_cycles"],
                        record.hardware_iterative_cycles,
                    )
                    if record.hardware_iterative_cycles > 0
                    else 0.0
                ),
                "total_absolute_error_percent": absolute_error_percent(
                    prediction["total_cycles"], hardware_total
                ),
            }
        )
    return rows


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
