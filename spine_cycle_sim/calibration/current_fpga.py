"""Calibration helpers for the current Spine and sharded-K4 FPGA systems.

The simulator remains the execution model.  Calibration applies one positive
scale per architecture/algorithm (or per observable component) and never uses
holdout rows when fitting that scale.
"""

from __future__ import annotations

from dataclasses import dataclass
import itertools
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
    simulator_level_checks: float = 0.0
    simulator_memory_requests: float = 0.0
    simulator_processed_edges: float = 0.0
    simulator_reader_parent_requests: float = 0.0
    simulator_hot_vertex_iterations: float = 0.0


@dataclass(frozen=True)
class ComposedTimingModel:
    """HLS-structured timing model for the current routed Spine design."""

    architecture: str
    algorithm: str
    maintenance_scale: float
    iterative_fixed_cycles_per_iteration: float
    iterative_simulator_scale: float
    iterative_strategy: str
    calibration_datasets: tuple[str, ...]
    maintenance_fixed_cycles: float = 0.0
    iterative_level_check_cycles: float = 0.0
    iterative_memory_request_cycles: float = 0.0
    iterative_processed_edge_cycles: float = 0.0
    iterative_reader_parent_request_cycles: float = 0.0
    iterative_hot_vertex_cycles: float = 0.0

    def predict_components(
        self,
        simulator_maintenance_cycles: float,
        simulator_iterative_cycles: float,
        iterations: int,
        simulator_level_checks: float = 0.0,
        simulator_memory_requests: float = 0.0,
        simulator_processed_edges: float = 0.0,
        simulator_reader_parent_requests: float = 0.0,
        simulator_hot_vertex_iterations: float = 0.0,
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
        for value, name in (
            (simulator_level_checks, "simulator_level_checks"),
            (simulator_memory_requests, "simulator_memory_requests"),
            (simulator_processed_edges, "simulator_processed_edges"),
            (simulator_reader_parent_requests, "simulator_reader_parent_requests"),
            (simulator_hot_vertex_iterations, "simulator_hot_vertex_iterations"),
        ):
            if not math.isfinite(value) or value < 0:
                raise ValueError(f"{name} must be finite and non-negative")
        maintenance = (
            self.maintenance_fixed_cycles
            + self.maintenance_scale * simulator_maintenance_cycles
        )
        iterative = (
            self.iterative_fixed_cycles_per_iteration * iterations
            + self.iterative_simulator_scale * simulator_iterative_cycles
            + self.iterative_level_check_cycles * simulator_level_checks
            + self.iterative_memory_request_cycles * simulator_memory_requests
            + self.iterative_processed_edge_cycles * simulator_processed_edges
            + self.iterative_reader_parent_request_cycles
            * simulator_reader_parent_requests
            + self.iterative_hot_vertex_cycles * simulator_hot_vertex_iterations
        )
        return {
            "maintenance_cycles": maintenance,
            "iterative_cycles": iterative,
            "total_cycles": maintenance + iterative,
        }


@dataclass(frozen=True)
class CurrentFPGAOverlapRecord:
    """One routed reader/compute observation and its simulator work ledger."""

    architecture: str
    algorithm: str
    profile_id: str
    dataset: str
    role: str
    iterations: int
    simulator_maintenance_cycles: float
    simulator_reader_cycles: float
    simulator_compute_cycles: float
    simulator_reader_memory_requests: float
    simulator_reader_level_cache_words: float
    simulator_compute_active_scan_words: float
    simulator_processed_edges: float
    hardware_maintenance_cycles: float
    hardware_reader_cycles: float
    hardware_compute_cycles: float
    hardware_iterative_span_cycles: float


@dataclass(frozen=True)
class OverlapTimingModel:
    """Component model that preserves reader/compute overlap."""

    architecture: str
    algorithm: str
    calibration_datasets: tuple[str, ...]
    maintenance_fixed_cycles: float
    maintenance_scale: float
    reader_simulator_scale: float
    reader_memory_request_cycles: float
    reader_level_cache_word_cycles: float
    compute_simulator_scale: float
    compute_active_scan_word_cycles: float
    compute_processed_edge_cycles: float
    span_residual_cycles_per_iteration: float

    def predict_components(
        self,
        *,
        iterations: int,
        simulator_maintenance_cycles: float,
        simulator_reader_cycles: float,
        simulator_compute_cycles: float,
        simulator_reader_memory_requests: float,
        simulator_reader_level_cache_words: float,
        simulator_compute_active_scan_words: float,
        simulator_processed_edges: float,
    ) -> dict[str, float]:
        if iterations <= 0:
            raise ValueError("overlap timing requires at least one iteration")
        for value, name in (
            (simulator_maintenance_cycles, "simulator_maintenance_cycles"),
            (simulator_reader_cycles, "simulator_reader_cycles"),
            (simulator_compute_cycles, "simulator_compute_cycles"),
        ):
            _require_positive_finite(value, name)
        for value, name in (
            (
                simulator_reader_memory_requests,
                "simulator_reader_memory_requests",
            ),
            (
                simulator_reader_level_cache_words,
                "simulator_reader_level_cache_words",
            ),
            (
                simulator_compute_active_scan_words,
                "simulator_compute_active_scan_words",
            ),
            (simulator_processed_edges, "simulator_processed_edges"),
        ):
            if not math.isfinite(value) or value < 0:
                raise ValueError(f"{name} must be finite and non-negative")
        maintenance = (
            self.maintenance_fixed_cycles
            + self.maintenance_scale * simulator_maintenance_cycles
        )
        reader = (
            self.reader_simulator_scale * simulator_reader_cycles
            + self.reader_memory_request_cycles
            * simulator_reader_memory_requests
            + self.reader_level_cache_word_cycles
            * simulator_reader_level_cache_words
        )
        compute = (
            self.compute_simulator_scale * simulator_compute_cycles
            + self.compute_active_scan_word_cycles
            * simulator_compute_active_scan_words
            + self.compute_processed_edge_cycles * simulator_processed_edges
        )
        iterative_span = (
            max(reader, compute)
            + self.span_residual_cycles_per_iteration * iterations
        )
        return {
            "maintenance_cycles": maintenance,
            "reader_cycles": reader,
            "compute_cycles": compute,
            "iterative_span_cycles": iterative_span,
            "total_cycles": maintenance + iterative_span,
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


def _solve_linear_system(
    matrix: list[list[float]], vector: list[float]
) -> list[float] | None:
    size = len(vector)
    augmented = [matrix[row][:] + [vector[row]] for row in range(size)]
    for pivot in range(size):
        selected = max(
            range(pivot, size), key=lambda row: abs(augmented[row][pivot])
        )
        if abs(augmented[selected][pivot]) < 1e-12:
            return None
        augmented[pivot], augmented[selected] = (
            augmented[selected],
            augmented[pivot],
        )
        scale = augmented[pivot][pivot]
        augmented[pivot] = [value / scale for value in augmented[pivot]]
        for row in range(size):
            if row == pivot:
                continue
            factor = augmented[row][pivot]
            augmented[row] = [
                value - factor * pivot_value
                for value, pivot_value in zip(augmented[row], augmented[pivot])
            ]
    return [augmented[row][-1] for row in range(size)]


def _fit_nonnegative_feature_model(
    features: list[tuple[float, ...]], targets: list[float]
) -> tuple[float, ...]:
    """Fit a small NNLS model by enumerating active coefficient sets."""

    if not features or len(features) != len(targets):
        raise ValueError("feature fit requires aligned rows")
    width = len(features[0])
    if width < 1 or width > 3 or any(len(row) != width for row in features):
        raise ValueError("feature fit supports one to three aligned columns")
    scales = [max(row[column] for row in features) for column in range(width)]
    if any(scale <= 0 for scale in scales):
        raise ValueError("feature fit requires positive variation in every column")
    normalized = [
        tuple(value / scales[column] for column, value in enumerate(row))
        for row in features
    ]
    best_error = math.inf
    best = [0.0] * width
    for active_width in range(1, width + 1):
        for active in itertools.combinations(range(width), active_width):
            gram = [
                [
                    sum(row[left] * row[right] for row in normalized)
                    for right in active
                ]
                for left in active
            ]
            rhs = [
                sum(row[column] * target for row, target in zip(normalized, targets))
                for column in active
            ]
            solved = _solve_linear_system(gram, rhs)
            if solved is None or any(value < -1e-9 for value in solved):
                continue
            candidate = [0.0] * width
            for column, value in zip(active, solved):
                candidate[column] = max(0.0, value)
            error = sum(
                (
                    sum(coefficient * value for coefficient, value in zip(candidate, row))
                    - target
                )
                ** 2
                for row, target in zip(normalized, targets)
            )
            if error < best_error:
                best_error = error
                best = candidate
    if not math.isfinite(best_error):
        raise ValueError("non-negative feature fit has no feasible solution")
    return tuple(value / scale for value, scale in zip(best, scales))


def fit_overlap_timing_model(
    records: Iterable[CurrentFPGAOverlapRecord],
) -> OverlapTimingModel:
    """Fit routed maintenance, reader, compute, and overlap components."""

    rows = tuple(records)
    if not rows:
        raise ValueError("overlap timing calibration requires records")
    identities = {(row.architecture, row.algorithm, row.profile_id) for row in rows}
    if len(identities) != 1:
        raise ValueError("overlap fit must contain one architecture/algorithm/profile")
    for row in rows:
        _validate_composed_role(row.role)
        if row.iterations <= 0:
            raise ValueError("overlap records require at least one iteration")
        for value, name in (
            (row.simulator_maintenance_cycles, "simulator_maintenance_cycles"),
            (row.simulator_reader_cycles, "simulator_reader_cycles"),
            (row.simulator_compute_cycles, "simulator_compute_cycles"),
            (row.hardware_maintenance_cycles, "hardware_maintenance_cycles"),
            (row.hardware_reader_cycles, "hardware_reader_cycles"),
            (row.hardware_compute_cycles, "hardware_compute_cycles"),
            (
                row.hardware_iterative_span_cycles,
                "hardware_iterative_span_cycles",
            ),
        ):
            _require_positive_finite(value, name)
        for value, name in (
            (
                row.simulator_reader_memory_requests,
                "simulator_reader_memory_requests",
            ),
            (
                row.simulator_reader_level_cache_words,
                "simulator_reader_level_cache_words",
            ),
            (
                row.simulator_compute_active_scan_words,
                "simulator_compute_active_scan_words",
            ),
            (row.simulator_processed_edges, "simulator_processed_edges"),
        ):
            if not math.isfinite(value) or value < 0:
                raise ValueError(f"{name} must be finite and non-negative")
        if row.hardware_iterative_span_cycles < max(
            row.hardware_reader_cycles, row.hardware_compute_cycles
        ):
            raise ValueError("hardware span cannot be shorter than either component")

    calibration = tuple(row for row in rows if row.role == "calibration")
    validation = tuple(row for row in rows if row.role != "calibration")
    if len(calibration) < 4:
        raise ValueError("overlap fit requires at least four calibration rows")
    if {row.dataset for row in calibration} & {row.dataset for row in validation}:
        raise ValueError("calibration and validation datasets overlap")

    maintenance_fixed, maintenance_scale = _fit_nonnegative_two_feature_model(
        [(1.0, row.simulator_maintenance_cycles) for row in calibration],
        [row.hardware_maintenance_cycles for row in calibration],
    )
    reader_scale, reader_request_cycles, reader_level_cache_cycles = (
        _fit_nonnegative_feature_model(
            [
                (
                    row.simulator_reader_cycles,
                    row.simulator_reader_memory_requests,
                    row.simulator_reader_level_cache_words,
                )
                for row in calibration
            ],
            [row.hardware_reader_cycles for row in calibration],
        )
    )
    compute_scale, compute_scan_cycles, compute_edge_cycles = (
        _fit_nonnegative_feature_model(
            [
                (
                    row.simulator_compute_cycles,
                    row.simulator_compute_active_scan_words,
                    row.simulator_processed_edges,
                )
                for row in calibration
            ],
            [row.hardware_compute_cycles for row in calibration],
        )
    )
    span_residual = _fit_nonnegative_feature_model(
        [(float(row.iterations),) for row in calibration],
        [
            row.hardware_iterative_span_cycles
            - max(row.hardware_reader_cycles, row.hardware_compute_cycles)
            for row in calibration
        ],
    )[0]
    architecture, algorithm, _profile_id = next(iter(identities))
    return OverlapTimingModel(
        architecture=architecture,
        algorithm=algorithm,
        calibration_datasets=tuple(sorted(row.dataset for row in calibration)),
        maintenance_fixed_cycles=maintenance_fixed,
        maintenance_scale=maintenance_scale,
        reader_simulator_scale=reader_scale,
        reader_memory_request_cycles=reader_request_cycles,
        reader_level_cache_word_cycles=reader_level_cache_cycles,
        compute_simulator_scale=compute_scale,
        compute_active_scan_word_cycles=compute_scan_cycles,
        compute_processed_edge_cycles=compute_edge_cycles,
        span_residual_cycles_per_iteration=span_residual,
    )


def overlap_prediction_rows(
    records: Iterable[CurrentFPGAOverlapRecord], model: OverlapTimingModel
) -> list[dict[str, object]]:
    """Apply an overlap timing model without refitting validation rows."""

    rows: list[dict[str, object]] = []
    for record in records:
        if (record.architecture, record.algorithm) != (
            model.architecture,
            model.algorithm,
        ):
            raise ValueError("overlap timing model identity does not match record")
        prediction = model.predict_components(
            iterations=record.iterations,
            simulator_maintenance_cycles=record.simulator_maintenance_cycles,
            simulator_reader_cycles=record.simulator_reader_cycles,
            simulator_compute_cycles=record.simulator_compute_cycles,
            simulator_reader_memory_requests=(
                record.simulator_reader_memory_requests
            ),
            simulator_reader_level_cache_words=(
                record.simulator_reader_level_cache_words
            ),
            simulator_compute_active_scan_words=(
                record.simulator_compute_active_scan_words
            ),
            simulator_processed_edges=record.simulator_processed_edges,
        )
        hardware_total = (
            record.hardware_maintenance_cycles
            + record.hardware_iterative_span_cycles
        )
        row = {
            **record.__dict__,
            "hardware_total_cycles": hardware_total,
            "predicted_maintenance_cycles": prediction["maintenance_cycles"],
            "predicted_reader_cycles": prediction["reader_cycles"],
            "predicted_compute_cycles": prediction["compute_cycles"],
            "predicted_iterative_span_cycles": prediction[
                "iterative_span_cycles"
            ],
            "predicted_total_cycles": prediction["total_cycles"],
        }
        for component in ("maintenance", "reader", "compute"):
            row[f"{component}_absolute_error_percent"] = absolute_error_percent(
                float(prediction[f"{component}_cycles"]),
                float(getattr(record, f"hardware_{component}_cycles")),
            )
        row["iterative_span_absolute_error_percent"] = absolute_error_percent(
            prediction["iterative_span_cycles"],
            record.hardware_iterative_span_cycles,
        )
        row["total_absolute_error_percent"] = absolute_error_percent(
            prediction["total_cycles"], hardware_total
        )
        rows.append(row)
    return rows


def fit_composed_timing_model(
    records: Iterable[CurrentFPGAComposedRecord],
    *,
    iterative_strategy: str = "fixed_plus_simulator",
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
        for value, name in (
            (row.simulator_level_checks, "simulator_level_checks"),
            (row.simulator_memory_requests, "simulator_memory_requests"),
            (row.simulator_processed_edges, "simulator_processed_edges"),
            (
                row.simulator_reader_parent_requests,
                "simulator_reader_parent_requests",
            ),
            (row.simulator_hot_vertex_iterations, "simulator_hot_vertex_iterations"),
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
    supported_strategies = {
        "fixed_plus_simulator",
        "simulator_scale_only",
        "hls_sssp_realized_work",
        "hls_cc_realized_work",
    }
    if iterative_strategy not in supported_strategies:
        raise ValueError(f"unsupported iterative strategy: {iterative_strategy!r}")
    minimum_iterative_rows = {
        "fixed_plus_simulator": 2,
        "simulator_scale_only": 1,
        "hls_sssp_realized_work": 3,
        "hls_cc_realized_work": 2,
    }[iterative_strategy]
    if len(iterative_calibration) < minimum_iterative_rows:
        raise ValueError(
            f"{iterative_strategy} requires {minimum_iterative_rows} "
            "propagating calibration row(s)"
        )

    maintenance_fixed, maintenance_scale = _fit_nonnegative_two_feature_model(
        [(1.0, row.simulator_maintenance_cycles) for row in calibration],
        [row.hardware_maintenance_cycles for row in calibration],
    )
    level_check_cycles = 0.0
    memory_request_cycles = 0.0
    processed_edge_cycles = 0.0
    reader_parent_request_cycles = 0.0
    hot_vertex_cycles = 0.0
    if iterative_strategy == "fixed_plus_simulator":
        fixed, simulator_scale = _fit_nonnegative_two_feature_model(
            [
                (float(row.iterations), row.simulator_iterative_cycles)
                for row in iterative_calibration
            ],
            [row.hardware_iterative_cycles for row in iterative_calibration],
        )
    elif iterative_strategy == "simulator_scale_only":
        fixed = 0.0
        simulator_scale = _geometric_mean(
            row.hardware_iterative_cycles / row.simulator_iterative_cycles
            for row in iterative_calibration
        )
    elif iterative_strategy == "hls_sssp_realized_work":
        fixed = 0.0
        simulator_scale, level_check_cycles, memory_request_cycles = (
            _fit_nonnegative_feature_model(
                [
                    (
                        row.simulator_iterative_cycles,
                        row.simulator_level_checks,
                        row.simulator_memory_requests,
                    )
                    for row in iterative_calibration
                ],
                [row.hardware_iterative_cycles for row in iterative_calibration],
            )
        )
    else:
        simulator_scale = 0.0
        fixed, reader_parent_request_cycles, hot_vertex_cycles = (
            _fit_nonnegative_feature_model(
                [
                    (
                        float(row.iterations),
                        row.simulator_reader_parent_requests,
                        row.simulator_hot_vertex_iterations,
                    )
                    for row in iterative_calibration
                ],
                [row.hardware_iterative_cycles for row in iterative_calibration],
            )
        )
    architecture, algorithm, _profile_id = next(iter(identities))
    return ComposedTimingModel(
        architecture=architecture,
        algorithm=algorithm,
        maintenance_scale=maintenance_scale,
        iterative_fixed_cycles_per_iteration=fixed,
        iterative_simulator_scale=simulator_scale,
        iterative_strategy=iterative_strategy,
        calibration_datasets=tuple(sorted(row.dataset for row in calibration)),
        maintenance_fixed_cycles=maintenance_fixed,
        iterative_level_check_cycles=level_check_cycles,
        iterative_memory_request_cycles=memory_request_cycles,
        iterative_processed_edge_cycles=processed_edge_cycles,
        iterative_reader_parent_request_cycles=reader_parent_request_cycles,
        iterative_hot_vertex_cycles=hot_vertex_cycles,
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
            record.simulator_level_checks,
            record.simulator_memory_requests,
            record.simulator_processed_edges,
            record.simulator_reader_parent_requests,
            record.simulator_hot_vertex_iterations,
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
                "simulator_level_checks": record.simulator_level_checks,
                "simulator_memory_requests": record.simulator_memory_requests,
                "simulator_processed_edges": record.simulator_processed_edges,
                "simulator_reader_parent_requests": (
                    record.simulator_reader_parent_requests
                ),
                "simulator_hot_vertex_iterations": (
                    record.simulator_hot_vertex_iterations
                ),
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
