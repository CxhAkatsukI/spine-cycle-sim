"""Calibration helpers for the current Spine and sharded-K4 FPGA systems.

The simulator remains the execution model.  Calibration applies one positive
scale per architecture/algorithm (or per observable component) and never uses
holdout rows when fitting that scale.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, replace
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
class GrasuUpdateControlRecord:
    """G+R update timing paired with the serialized nonempty-shard launches."""

    algorithm: str
    profile_id: str
    dataset: str
    role: str
    simulator_update_cycles: float
    nonempty_destination_shards: int
    hardware_update_cycles: float


@dataclass(frozen=True)
class GrasuUpdateControlModel:
    """Execution time plus one routed control envelope per nonempty PMA shard."""

    algorithm: str
    profile_id: str
    calibration_datasets: tuple[str, ...]
    control_cycles_per_nonempty_shard: float

    def predict(
        self, *, simulator_update_cycles: float, nonempty_destination_shards: int
    ) -> float:
        _require_positive_finite(simulator_update_cycles, "simulator_update_cycles")
        if nonempty_destination_shards <= 0:
            raise ValueError("nonempty_destination_shards must be positive")
        return (
            simulator_update_cycles
            + self.control_cycles_per_nonempty_shard
            * nonempty_destination_shards
        )


@dataclass(frozen=True)
class GrasuPersistentLaunchModel:
    """Warm batch launch plus serialized envelopes after the first shard."""

    algorithm: str
    profile_id: str
    development_datasets: tuple[str, ...]
    batch_launch_cycles: float
    post_first_shard_cycles: float

    def predict(
        self, *, simulator_update_cycles: float, nonempty_destination_shards: int
    ) -> float:
        _require_positive_finite(simulator_update_cycles, "simulator_update_cycles")
        if nonempty_destination_shards <= 0:
            raise ValueError("nonempty_destination_shards must be positive")
        return (
            simulator_update_cycles
            + self.batch_launch_cycles
            + self.post_first_shard_cycles * (nonempty_destination_shards - 1)
        )


@dataclass(frozen=True)
class SpineRealizedWorkRecord:
    """Routed Spine timing paired with execution-driven HLS work counters."""

    algorithm: str
    profile_id: str
    dataset: str
    role: str
    rounds: int
    range_tasks: float
    processed_edges: float
    hardware_reader_cycles: float
    hardware_compute_cycles: float
    hardware_iterative_span_cycles: float


@dataclass(frozen=True)
class SpineRealizedWorkModel:
    """Shared reader/compute model for the routed owner-FIFO Spine kernels."""

    calibration_datasets: tuple[str, ...]
    reader_round_cycles: float
    reader_processed_edge_cycles: float
    compute_round_cycles: float
    compute_range_task_cycles: float
    compute_processed_edge_cycles: float
    span_round_cycles: float
    span_range_task_cycles: float
    span_processed_edge_cycles: float

    def predict_components(
        self, *, rounds: int, range_tasks: float, processed_edges: float
    ) -> dict[str, float]:
        if rounds <= 0:
            raise ValueError("realized-work timing requires at least one round")
        for value, name in (
            (range_tasks, "range_tasks"),
            (processed_edges, "processed_edges"),
        ):
            if not math.isfinite(value) or value < 0:
                raise ValueError(f"{name} must be finite and non-negative")
        reader = (
            self.reader_round_cycles * rounds
            + self.reader_processed_edge_cycles * processed_edges
        )
        compute = (
            self.compute_round_cycles * rounds
            + self.compute_range_task_cycles * range_tasks
            + self.compute_processed_edge_cycles * processed_edges
        )
        span = (
            self.span_round_cycles * rounds
            + self.span_range_task_cycles * range_tasks
            + self.span_processed_edge_cycles * processed_edges
        )
        return {
            "reader_cycles": reader,
            "compute_cycles": compute,
            "iterative_span_cycles": span,
        }


@dataclass(frozen=True)
class SpineComponentFeatureRecord:
    """Routed timing paired with simulator component work and AXI requests."""

    algorithm: str
    profile_id: str
    dataset: str
    role: str
    rounds: int
    simulator_maintenance_cycles: float
    simulator_reader_cycles: float
    simulator_compute_cycles: float
    simulator_reader_memory_requests: float
    simulator_compute_memory_requests: float
    hardware_maintenance_cycles: float
    hardware_reader_cycles: float
    hardware_compute_cycles: float
    hardware_iterative_span_cycles: float


@dataclass(frozen=True)
class SpineComponentFeatureModel:
    """Per-algorithm timing map that preserves routed reader/compute overlap."""

    algorithm: str
    profile_id: str
    calibration_datasets: tuple[str, ...]
    maintenance_fixed_cycles: float
    maintenance_simulator_scale: float
    reader_memory_request_cycles: float
    reader_simulator_cycle_scale: float
    compute_round_cycles: float
    compute_memory_request_cycles: float
    compute_simulator_cycle_scale: float
    span_residual_cycles_per_round: float

    def predict_components(
        self,
        *,
        rounds: int,
        simulator_maintenance_cycles: float,
        simulator_reader_cycles: float,
        simulator_compute_cycles: float,
        simulator_reader_memory_requests: float,
        simulator_compute_memory_requests: float,
    ) -> dict[str, float]:
        _require_positive_finite(
            simulator_maintenance_cycles, "simulator_maintenance_cycles"
        )
        for value, name in (
            (simulator_reader_cycles, "simulator_reader_cycles"),
            (simulator_compute_cycles, "simulator_compute_cycles"),
            (
                simulator_reader_memory_requests,
                "simulator_reader_memory_requests",
            ),
            (
                simulator_compute_memory_requests,
                "simulator_compute_memory_requests",
            ),
        ):
            if not math.isfinite(value) or value < 0:
                raise ValueError(f"{name} must be finite and non-negative")
        if rounds < 0:
            raise ValueError("rounds must be non-negative")

        maintenance = (
            self.maintenance_fixed_cycles
            + self.maintenance_simulator_scale * simulator_maintenance_cycles
        )
        if rounds == 0:
            if any(
                value != 0
                for value in (
                    simulator_reader_cycles,
                    simulator_compute_cycles,
                    simulator_reader_memory_requests,
                    simulator_compute_memory_requests,
                )
            ):
                raise ValueError("zero-round timing cannot contain iterative work")
            return {
                "maintenance_cycles": maintenance,
                "reader_cycles": 0.0,
                "compute_cycles": 0.0,
                "iterative_span_cycles": 0.0,
                "total_cycles": maintenance,
            }

        reader = (
            self.reader_memory_request_cycles * simulator_reader_memory_requests
            + self.reader_simulator_cycle_scale * simulator_reader_cycles
        )
        compute = (
            self.compute_round_cycles * rounds
            + self.compute_memory_request_cycles * simulator_compute_memory_requests
            + self.compute_simulator_cycle_scale * simulator_compute_cycles
        )
        iterative_span = (
            max(reader, compute)
            + self.span_residual_cycles_per_round * rounds
        )
        return {
            "maintenance_cycles": maintenance,
            "reader_cycles": reader,
            "compute_cycles": compute,
            "iterative_span_cycles": iterative_span,
            "total_cycles": maintenance + iterative_span,
        }


@dataclass(frozen=True)
class SpineMechanismComponentRecord:
    """Routed timing paired with non-overlapping HLS mechanism features."""

    algorithm: str
    profile_id: str
    dataset: str
    role: str
    rounds: int
    vertices: float
    simulator_maintenance_cycles: float
    simulator_reader_cycles: float
    simulator_compute_cycles: float
    simulator_reader_memory_requests: float
    simulator_compute_memory_requests: float
    hardware_maintenance_cycles: float
    hardware_reader_cycles: float
    hardware_compute_cycles: float
    hardware_iterative_span_cycles: float


@dataclass(frozen=True)
class SpineMechanismComponentModel:
    """HLS mechanism model that preserves routed reader/compute overlap.

    The reader event includes launch work, request service, and the full-domain
    publication sweep observed through stream backpressure.  Compute timing is
    mapped from its execution-driven span, which already includes AXI service
    and bounded-pipeline stalls; adding request count again would double count
    that work.
    """

    algorithm: str
    profile_id: str
    calibration_datasets: tuple[str, ...]
    maintenance_fixed_cycles: float
    maintenance_simulator_scale: float
    reader_round_cycles: float
    reader_vertex_cycles: float
    reader_memory_request_cycles: float
    compute_fixed_cycles: float
    compute_round_cycles: float
    compute_memory_request_cycles: float
    compute_simulator_cycle_scale: float
    compute_strategy: str
    span_residual_cycles_per_round: float

    def predict_components(
        self,
        *,
        rounds: int,
        vertices: float,
        simulator_maintenance_cycles: float,
        simulator_reader_cycles: float,
        simulator_compute_cycles: float,
        simulator_reader_memory_requests: float,
        simulator_compute_memory_requests: float,
    ) -> dict[str, float]:
        _require_positive_finite(vertices, "vertices")
        _require_positive_finite(
            simulator_maintenance_cycles, "simulator_maintenance_cycles"
        )
        for value, name in (
            (simulator_reader_cycles, "simulator_reader_cycles"),
            (simulator_compute_cycles, "simulator_compute_cycles"),
            (
                simulator_reader_memory_requests,
                "simulator_reader_memory_requests",
            ),
            (
                simulator_compute_memory_requests,
                "simulator_compute_memory_requests",
            ),
        ):
            if not math.isfinite(value) or value < 0:
                raise ValueError(f"{name} must be finite and non-negative")
        if rounds < 0:
            raise ValueError("rounds must be non-negative")

        maintenance = (
            self.maintenance_fixed_cycles
            + self.maintenance_simulator_scale * simulator_maintenance_cycles
        )
        if rounds == 0:
            if any(
                value != 0
                for value in (
                    simulator_reader_cycles,
                    simulator_compute_cycles,
                    simulator_reader_memory_requests,
                    simulator_compute_memory_requests,
                )
            ):
                raise ValueError("zero-round timing cannot contain iterative work")
            return {
                "maintenance_cycles": maintenance,
                "reader_cycles": 0.0,
                "compute_cycles": 0.0,
                "iterative_span_cycles": 0.0,
                "total_cycles": maintenance,
            }

        reader = (
            self.reader_round_cycles * rounds
            + self.reader_vertex_cycles * vertices
            + self.reader_memory_request_cycles
            * simulator_reader_memory_requests
        )
        compute = (
            self.compute_fixed_cycles
            + self.compute_round_cycles * rounds
            + self.compute_memory_request_cycles
            * simulator_compute_memory_requests
            + self.compute_simulator_cycle_scale * simulator_compute_cycles
        )
        iterative_span = (
            max(reader, compute)
            + self.span_residual_cycles_per_round * rounds
        )
        return {
            "maintenance_cycles": maintenance,
            "reader_cycles": reader,
            "compute_cycles": compute,
            "iterative_span_cycles": iterative_span,
            "total_cycles": maintenance + iterative_span,
        }


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
    simulator_vertices: float
    simulator_maintenance_cycles: float
    simulator_reader_cycles: float
    simulator_compute_cycles: float
    simulator_reader_memory_requests: float
    simulator_reader_level_cache_words: float
    simulator_reader_range_tasks: float
    simulator_reader_credit_stall_cycles: float
    simulator_compute_active_scan_words: float
    simulator_compute_range_tasks: float
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
    reader_memory_request_cycles: float
    reader_round_cycles: float
    reader_vertex_cycles: float
    compute_round_cycles: float
    compute_range_task_cycles: float
    compute_processed_edge_cycles: float
    span_residual_cycles_per_iteration: float

    def predict_components(
        self,
        *,
        iterations: int,
        simulator_vertices: float,
        simulator_maintenance_cycles: float,
        simulator_reader_cycles: float,
        simulator_compute_cycles: float,
        simulator_reader_memory_requests: float,
        simulator_reader_level_cache_words: float,
        simulator_reader_range_tasks: float,
        simulator_reader_credit_stall_cycles: float,
        simulator_compute_active_scan_words: float,
        simulator_compute_range_tasks: float,
        simulator_processed_edges: float,
    ) -> dict[str, float]:
        if iterations <= 0:
            raise ValueError("overlap timing requires at least one iteration")
        for value, name in (
            (simulator_vertices, "simulator_vertices"),
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
            (simulator_reader_range_tasks, "simulator_reader_range_tasks"),
            (
                simulator_reader_credit_stall_cycles,
                "simulator_reader_credit_stall_cycles",
            ),
            (
                simulator_compute_active_scan_words,
                "simulator_compute_active_scan_words",
            ),
            (simulator_compute_range_tasks, "simulator_compute_range_tasks"),
            (simulator_processed_edges, "simulator_processed_edges"),
        ):
            if not math.isfinite(value) or value < 0:
                raise ValueError(f"{name} must be finite and non-negative")
        maintenance = (
            self.maintenance_fixed_cycles
            + self.maintenance_scale * simulator_maintenance_cycles
        )
        reader = (
            self.reader_memory_request_cycles
            * simulator_reader_memory_requests
            + self.reader_round_cycles * iterations
            + self.reader_vertex_cycles * simulator_vertices
        )
        compute = (
            self.compute_round_cycles * iterations
            + self.compute_range_task_cycles * simulator_compute_range_tasks
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


@dataclass(frozen=True)
class CurrentFPGAOverlapV6Record:
    """Routed overlap observation with explicit cross-batch HLS work terms."""

    architecture: str
    algorithm: str
    profile_id: str
    dataset: str
    role: str
    iterations: int
    simulator_vertices: float
    simulator_maintenance_cycles: float
    simulator_reader_cycles: float
    simulator_compute_cycles: float
    simulator_reader_memory_requests: float
    simulator_reader_metadata_bytes: float
    simulator_reader_source_requests: float
    simulator_compute_memory_requests: float
    simulator_compute_sparse_store_scan_words: float
    simulator_processed_edges: float
    hardware_maintenance_cycles: float
    hardware_reader_cycles: float
    hardware_compute_cycles: float
    hardware_iterative_span_cycles: float


@dataclass(frozen=True)
class OverlapTimingV6Model:
    """Cross-batch component model mapped to routed HLS loop work."""

    architecture: str
    algorithm: str
    calibration_datasets: tuple[str, ...]
    maintenance_fixed_cycles: float
    maintenance_scale: float
    reader_round_cycles: float
    reader_memory_request_cycles: float
    reader_metadata_byte_cycles: float
    reader_vertex_cycles: float
    compute_round_cycles: float
    compute_memory_request_cycles: float
    compute_sparse_store_scan_word_cycles: float
    compute_processed_edge_cycles: float
    span_residual_cycles_per_iteration: float

    def predict_components(
        self,
        *,
        iterations: int,
        simulator_vertices: float,
        simulator_maintenance_cycles: float,
        simulator_reader_cycles: float,
        simulator_compute_cycles: float,
        simulator_reader_memory_requests: float,
        simulator_reader_metadata_bytes: float,
        simulator_reader_source_requests: float,
        simulator_compute_memory_requests: float,
        simulator_compute_sparse_store_scan_words: float,
        simulator_processed_edges: float,
    ) -> dict[str, float]:
        if iterations <= 0:
            raise ValueError("overlap-v6 timing requires at least one iteration")
        for value, name in (
            (simulator_vertices, "simulator_vertices"),
            (simulator_maintenance_cycles, "simulator_maintenance_cycles"),
            (simulator_reader_cycles, "simulator_reader_cycles"),
            (simulator_compute_cycles, "simulator_compute_cycles"),
        ):
            _require_positive_finite(value, name)
        for value, name in (
            (simulator_reader_memory_requests, "simulator_reader_memory_requests"),
            (simulator_reader_metadata_bytes, "simulator_reader_metadata_bytes"),
            (simulator_reader_source_requests, "simulator_reader_source_requests"),
            (simulator_compute_memory_requests, "simulator_compute_memory_requests"),
            (
                simulator_compute_sparse_store_scan_words,
                "simulator_compute_sparse_store_scan_words",
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
            self.reader_round_cycles * iterations
            + self.reader_memory_request_cycles * simulator_reader_memory_requests
            + self.reader_metadata_byte_cycles * simulator_reader_metadata_bytes
            + self.reader_vertex_cycles * simulator_vertices
        )
        compute = (
            self.compute_round_cycles * iterations
            + self.compute_memory_request_cycles * simulator_compute_memory_requests
            + self.compute_sparse_store_scan_word_cycles
            * simulator_compute_sparse_store_scan_words
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
    return fit_total_scale_calibration_only(calibration)


def fit_grasu_update_control_model(
    records: Iterable[GrasuUpdateControlRecord],
) -> GrasuUpdateControlModel:
    """Fit only the serialized shard control envelope from calibration rows."""

    rows = tuple(records)
    if len(rows) < 2:
        raise ValueError("G+R update control fit requires two calibration rows")
    identities = {(row.algorithm, row.profile_id) for row in rows}
    if len(identities) != 1:
        raise ValueError("G+R update control fit requires one algorithm/profile")
    if any(row.role != "calibration" for row in rows):
        raise ValueError("G+R update control fit rejects non-calibration rows")
    if len({row.dataset for row in rows}) != len(rows):
        raise ValueError("G+R update control calibration datasets must be unique")
    numerator = 0.0
    denominator = 0.0
    for row in rows:
        _require_positive_finite(
            row.simulator_update_cycles, "simulator_update_cycles"
        )
        _require_positive_finite(row.hardware_update_cycles, "hardware_update_cycles")
        if row.nonempty_destination_shards <= 0:
            raise ValueError("nonempty_destination_shards must be positive")
        residual = row.hardware_update_cycles - row.simulator_update_cycles
        if residual <= 0:
            raise ValueError("hardware update timing must exceed simulated dataflow")
        numerator += row.nonempty_destination_shards * residual
        denominator += row.nonempty_destination_shards**2
    control_cycles = numerator / denominator
    _require_positive_finite(control_cycles, "control_cycles_per_nonempty_shard")
    algorithm, profile_id = next(iter(identities))
    return GrasuUpdateControlModel(
        algorithm=algorithm,
        profile_id=profile_id,
        calibration_datasets=tuple(sorted(row.dataset for row in rows)),
        control_cycles_per_nonempty_shard=control_cycles,
    )


def fit_grasu_persistent_launch_model(
    records: Iterable[GrasuUpdateControlRecord],
) -> GrasuPersistentLaunchModel:
    """Fit a fixed warm launch and a serialized post-first-shard envelope."""

    rows = tuple(records)
    if len(rows) < 3:
        raise ValueError("persistent launch fit requires at least three development rows")
    identities = {(row.algorithm, row.profile_id) for row in rows}
    if len(identities) != 1:
        raise ValueError("persistent launch fit requires one algorithm/profile")
    if any(row.role != "calibration" for row in rows):
        raise ValueError("persistent launch fit rejects non-development rows")
    if len({row.dataset for row in rows}) != len(rows):
        raise ValueError("persistent launch development datasets must be unique")
    xs: list[float] = []
    ys: list[float] = []
    for row in rows:
        _require_positive_finite(row.simulator_update_cycles, "simulator_update_cycles")
        _require_positive_finite(row.hardware_update_cycles, "hardware_update_cycles")
        if row.nonempty_destination_shards <= 0:
            raise ValueError("nonempty_destination_shards must be positive")
        residual = row.hardware_update_cycles - row.simulator_update_cycles
        if residual <= 0:
            raise ValueError("hardware update timing must exceed simulated dataflow")
        xs.append(float(row.nonempty_destination_shards - 1))
        ys.append(residual)
    mean_x = statistics.fmean(xs)
    mean_y = statistics.fmean(ys)
    denominator = sum((value - mean_x) ** 2 for value in xs)
    unconstrained_slope = (
        sum((x - mean_x) * (y - mean_y) for x, y in zip(xs, ys)) / denominator
        if denominator > 0
        else 0.0
    )
    unconstrained_intercept = mean_y - unconstrained_slope * mean_x
    candidates = [
        (mean_y, 0.0),
        (
            0.0,
            max(0.0, sum(x * y for x, y in zip(xs, ys)) / sum(x * x for x in xs)),
        ) if any(xs) else (mean_y, 0.0),
    ]
    if unconstrained_intercept >= 0 and unconstrained_slope >= 0:
        candidates.append((unconstrained_intercept, unconstrained_slope))
    intercept, slope = min(
        candidates,
        key=lambda pair: sum(
            (y - pair[0] - pair[1] * x) ** 2 for x, y in zip(xs, ys)
        ),
    )
    if not all(math.isfinite(value) and value >= 0 for value in (intercept, slope)):
        raise ValueError("persistent launch coefficients must be finite and non-negative")
    algorithm, profile_id = next(iter(identities))
    return GrasuPersistentLaunchModel(
        algorithm=algorithm,
        profile_id=profile_id,
        development_datasets=tuple(sorted(row.dataset for row in rows)),
        batch_launch_cycles=intercept,
        post_first_shard_cycles=slope,
    )


def grasu_persistent_launch_prediction_rows(
    records: Iterable[GrasuUpdateControlRecord],
    model: GrasuPersistentLaunchModel,
) -> list[dict[str, object]]:
    output: list[dict[str, object]] = []
    for row in records:
        if (row.algorithm, row.profile_id) != (model.algorithm, model.profile_id):
            raise ValueError("persistent launch record/model identity mismatch")
        predicted = model.predict(
            simulator_update_cycles=row.simulator_update_cycles,
            nonempty_destination_shards=row.nonempty_destination_shards,
        )
        output.append(
            {
                "algorithm": row.algorithm,
                "profile_id": row.profile_id,
                "dataset": row.dataset,
                "role": row.role,
                "simulator_update_cycles": row.simulator_update_cycles,
                "nonempty_destination_shards": row.nonempty_destination_shards,
                "batch_launch_cycles": model.batch_launch_cycles,
                "post_first_shard_cycles": model.post_first_shard_cycles,
                "predicted_update_cycles": predicted,
                "hardware_update_cycles": row.hardware_update_cycles,
                "error_percent": 100.0 * (predicted - row.hardware_update_cycles)
                / row.hardware_update_cycles,
                "absolute_error_percent": absolute_error_percent(
                    predicted, row.hardware_update_cycles
                ),
            }
        )
    return output


def grasu_persistent_launch_leave_one_dataset_out_rows(
    records: Iterable[GrasuUpdateControlRecord],
) -> list[dict[str, object]]:
    rows = tuple(records)
    if len(rows) < 4:
        raise ValueError("persistent launch LODO requires at least four rows")
    output: list[dict[str, object]] = []
    for held_out in rows:
        training = tuple(row for row in rows if row.dataset != held_out.dataset)
        model = fit_grasu_persistent_launch_model(training)
        prediction = grasu_persistent_launch_prediction_rows((held_out,), model)[0]
        prediction["held_out_dataset"] = held_out.dataset
        prediction["training_datasets"] = ",".join(model.development_datasets)
        output.append(prediction)
    return output


def grasu_update_control_prediction_rows(
    records: Iterable[GrasuUpdateControlRecord],
    model: GrasuUpdateControlModel,
) -> list[dict[str, object]]:
    rows = []
    for record in records:
        if (record.algorithm, record.profile_id) != (
            model.algorithm,
            model.profile_id,
        ):
            raise ValueError("G+R update control record/model identity mismatch")
        predicted = model.predict(
            simulator_update_cycles=record.simulator_update_cycles,
            nonempty_destination_shards=record.nonempty_destination_shards,
        )
        rows.append(
            {
                "algorithm": record.algorithm,
                "profile_id": record.profile_id,
                "dataset": record.dataset,
                "role": record.role,
                "simulator_update_cycles": record.simulator_update_cycles,
                "nonempty_destination_shards": record.nonempty_destination_shards,
                "control_cycles_per_nonempty_shard": (
                    model.control_cycles_per_nonempty_shard
                ),
                "predicted_update_cycles": predicted,
                "hardware_update_cycles": record.hardware_update_cycles,
                "error_percent": 100.0
                * (predicted - record.hardware_update_cycles)
                / record.hardware_update_cycles,
                "absolute_error_percent": absolute_error_percent(
                    predicted, record.hardware_update_cycles
                ),
            }
        )
    return rows


def grasu_update_control_leave_one_dataset_out_rows(
    records: Iterable[GrasuUpdateControlRecord],
) -> list[dict[str, object]]:
    rows = tuple(records)
    if len(rows) < 2:
        raise ValueError("leave-one-dataset-out requires at least two rows")
    predictions: list[dict[str, object]] = []
    for held_out in rows:
        training = tuple(row for row in rows if row.dataset != held_out.dataset)
        if not training:
            raise ValueError("leave-one-dataset-out requires another dataset")
        if len(training) == 1:
            row = training[0]
            residual = row.hardware_update_cycles - row.simulator_update_cycles
            if residual <= 0 or row.nonempty_destination_shards <= 0:
                raise ValueError("invalid leave-one-dataset-out training row")
            model = GrasuUpdateControlModel(
                algorithm=row.algorithm,
                profile_id=row.profile_id,
                calibration_datasets=(row.dataset,),
                control_cycles_per_nonempty_shard=(
                    residual / row.nonempty_destination_shards
                ),
            )
        else:
            model = fit_grasu_update_control_model(training)
        prediction = grasu_update_control_prediction_rows((held_out,), model)[0]
        prediction["held_out_dataset"] = held_out.dataset
        prediction["training_datasets"] = ",".join(model.calibration_datasets)
        predictions.append(prediction)
    return predictions


def fit_total_scale_calibration_only(
    records: Iterable[CurrentFPGATimingRecord],
) -> PositiveScaleModel:
    """Freeze a total-cycle scale before any holdout row is available."""

    calibration = tuple(records)
    if len(calibration) < 2:
        raise ValueError("total-cycle freeze requires at least two calibration rows")
    identities = {
        (row.architecture, row.algorithm, row.profile_id) for row in calibration
    }
    if len(identities) != 1:
        raise ValueError(
            "total-cycle freeze must contain one architecture/algorithm/profile"
        )
    if any(row.role != "calibration" for row in calibration):
        raise ValueError("total-cycle freeze rejects non-calibration rows")
    if len({row.dataset for row in calibration}) != len(calibration):
        raise ValueError("total-cycle freeze requires distinct calibration datasets")
    for row in calibration:
        _require_positive_finite(row.simulator_cycles, "simulator_cycles")
        _require_positive_finite(row.hardware_cycles, "hardware_cycles")
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
    return fit_component_scale_calibration_only(calibration)


def fit_component_scale_calibration_only(
    records: Iterable[CurrentFPGAComponentRecord],
) -> PositiveScaleModel:
    """Freeze one observable component scale before holdout execution."""

    calibration = tuple(records)
    if len(calibration) < 2:
        raise ValueError("component freeze requires at least two calibration rows")
    identities = {
        (row.architecture, row.algorithm, row.profile_id, row.component)
        for row in calibration
    }
    if len(identities) != 1:
        raise ValueError(
            "component freeze must contain one architecture/algorithm/profile/component"
        )
    if any(row.role != "calibration" for row in calibration):
        raise ValueError("component freeze rejects non-calibration rows")
    if len({row.dataset for row in calibration}) != len(calibration):
        raise ValueError("component freeze requires distinct calibration datasets")
    observations = {row.hardware_observation for row in calibration}
    if len(observations) != 1 or not next(iter(observations)):
        raise ValueError("hardware component observation scope must be explicit and stable")
    for row in calibration:
        _require_positive_finite(row.simulator_cycles, "simulator_cycles")
        _require_positive_finite(row.hardware_cycles, "hardware_cycles")
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
    if width < 1 or width > 4 or any(len(row) != width for row in features):
        raise ValueError("feature fit supports one to four aligned columns")
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


def fit_spine_realized_work_model(
    records: Iterable[SpineRealizedWorkRecord],
) -> SpineRealizedWorkModel:
    """Fit one shared routed timing model using calibration rows only.

    Reader and compute use the same work quantities that the routed HLS reports:
    kernel rounds, range tasks, and processed edges.  The fit is shared across
    SSSP and CC because both use the same reader and owner-FIFO kernel structure.
    """

    rows = tuple(records)
    if len(rows) < 8:
        raise ValueError("realized-work fit requires at least eight calibration rows")
    if any(row.role != "calibration" for row in rows):
        raise ValueError("realized-work freeze rejects non-calibration rows")
    if {row.algorithm for row in rows} != {"weighted_sssp", "connected_components"}:
        raise ValueError("realized-work fit requires SSSP and CC calibration rows")
    dataset_algorithms: dict[str, set[str]] = {}
    for row in rows:
        if row.rounds <= 0:
            raise ValueError("realized-work calibration rows require positive rounds")
        for value, name in (
            (row.range_tasks, "range_tasks"),
            (row.processed_edges, "processed_edges"),
            (row.hardware_reader_cycles, "hardware_reader_cycles"),
            (row.hardware_compute_cycles, "hardware_compute_cycles"),
            (row.hardware_iterative_span_cycles, "hardware_iterative_span_cycles"),
        ):
            _require_positive_finite(value, name)
        if row.hardware_iterative_span_cycles < max(
            row.hardware_reader_cycles, row.hardware_compute_cycles
        ):
            raise ValueError("hardware span cannot be shorter than reader or compute")
        dataset_algorithms.setdefault(row.dataset, set()).add(row.algorithm)
    if len(dataset_algorithms) < 4 or any(
        algorithms != {"weighted_sssp", "connected_components"}
        for algorithms in dataset_algorithms.values()
    ):
        raise ValueError("realized-work fit requires paired algorithms on four datasets")

    reader_round, reader_edge = _fit_nonnegative_feature_model(
        [(float(row.rounds), row.processed_edges) for row in rows],
        [row.hardware_reader_cycles for row in rows],
    )
    compute_round, compute_task, compute_edge = _fit_nonnegative_feature_model(
        [
            (float(row.rounds), row.range_tasks, row.processed_edges)
            for row in rows
        ],
        [row.hardware_compute_cycles for row in rows],
    )
    span_round, span_task, span_edge = _fit_nonnegative_feature_model(
        [
            (float(row.rounds), row.range_tasks, row.processed_edges)
            for row in rows
        ],
        [row.hardware_iterative_span_cycles for row in rows],
    )
    return SpineRealizedWorkModel(
        calibration_datasets=tuple(sorted(dataset_algorithms)),
        reader_round_cycles=reader_round,
        reader_processed_edge_cycles=reader_edge,
        compute_round_cycles=compute_round,
        compute_range_task_cycles=compute_task,
        compute_processed_edge_cycles=compute_edge,
        span_round_cycles=span_round,
        span_range_task_cycles=span_task,
        span_processed_edge_cycles=span_edge,
    )


def spine_realized_work_prediction_rows(
    records: Iterable[SpineRealizedWorkRecord], model: SpineRealizedWorkModel
) -> list[dict[str, object]]:
    """Apply a frozen realized-work model without fitting validation rows."""

    rows: list[dict[str, object]] = []
    for record in records:
        prediction = model.predict_components(
            rounds=record.rounds,
            range_tasks=record.range_tasks,
            processed_edges=record.processed_edges,
        )
        row = {**asdict(record)}
        for component in ("reader", "compute", "iterative_span"):
            predicted = prediction[f"{component}_cycles"]
            hardware = float(getattr(record, f"hardware_{component}_cycles"))
            row[f"predicted_{component}_cycles"] = predicted
            row[f"{component}_absolute_error_percent"] = absolute_error_percent(
                predicted, hardware
            )
        rows.append(row)
    return rows


def fit_spine_component_feature_model(
    records: Iterable[SpineComponentFeatureRecord],
) -> SpineComponentFeatureModel:
    """Fit one algorithm without admitting validation rows.

    The feature form follows the routed split kernel: maintenance is an affine
    map of the simulator maintenance span, reader time is driven by AXI request
    service plus its execution-driven component span, and compute time adds one
    per-round control term. Reader and compute remain overlapped in the final
    iterative span.
    """

    rows = tuple(records)
    if len(rows) < 4:
        raise ValueError("component-feature freeze requires four calibration rows")
    if any(row.role != "calibration" for row in rows):
        raise ValueError("component-feature freeze rejects non-calibration rows")
    identities = {(row.algorithm, row.profile_id) for row in rows}
    if len(identities) != 1:
        raise ValueError("component-feature fit requires one algorithm/profile")
    if len({row.dataset for row in rows}) != len(rows):
        raise ValueError("component-feature fit requires distinct datasets")
    algorithm, profile_id = next(iter(identities))

    for row in rows:
        _require_positive_finite(
            row.simulator_maintenance_cycles, "simulator_maintenance_cycles"
        )
        _require_positive_finite(
            row.hardware_maintenance_cycles, "hardware_maintenance_cycles"
        )
        if row.rounds < 0:
            raise ValueError("rounds must be non-negative")

    maintenance_fixed, maintenance_scale = _fit_nonnegative_feature_model(
        [(1.0, row.simulator_maintenance_cycles) for row in rows],
        [row.hardware_maintenance_cycles for row in rows],
    )

    zero_round = all(row.rounds == 0 for row in rows)
    if zero_round:
        for row in rows:
            if any(
                value != 0
                for value in (
                    row.simulator_reader_cycles,
                    row.simulator_compute_cycles,
                    row.simulator_reader_memory_requests,
                    row.simulator_compute_memory_requests,
                    row.hardware_reader_cycles,
                    row.hardware_compute_cycles,
                    row.hardware_iterative_span_cycles,
                )
            ):
                raise ValueError("zero-round calibration contains iterative work")
        return SpineComponentFeatureModel(
            algorithm=algorithm,
            profile_id=profile_id,
            calibration_datasets=tuple(sorted(row.dataset for row in rows)),
            maintenance_fixed_cycles=maintenance_fixed,
            maintenance_simulator_scale=maintenance_scale,
            reader_memory_request_cycles=0.0,
            reader_simulator_cycle_scale=0.0,
            compute_round_cycles=0.0,
            compute_memory_request_cycles=0.0,
            compute_simulator_cycle_scale=0.0,
            span_residual_cycles_per_round=0.0,
        )
    if any(row.rounds <= 0 for row in rows):
        raise ValueError("iterative calibration cannot mix zero and positive rounds")

    for row in rows:
        for value, name in (
            (row.simulator_reader_cycles, "simulator_reader_cycles"),
            (row.simulator_compute_cycles, "simulator_compute_cycles"),
            (
                row.simulator_reader_memory_requests,
                "simulator_reader_memory_requests",
            ),
            (
                row.simulator_compute_memory_requests,
                "simulator_compute_memory_requests",
            ),
            (row.hardware_reader_cycles, "hardware_reader_cycles"),
            (row.hardware_compute_cycles, "hardware_compute_cycles"),
            (
                row.hardware_iterative_span_cycles,
                "hardware_iterative_span_cycles",
            ),
        ):
            _require_positive_finite(value, name)
        if row.hardware_iterative_span_cycles < max(
            row.hardware_reader_cycles, row.hardware_compute_cycles
        ):
            raise ValueError("hardware span cannot be shorter than its components")

    reader_request, reader_simulator = _fit_nonnegative_feature_model(
        [
            (row.simulator_reader_memory_requests, row.simulator_reader_cycles)
            for row in rows
        ],
        [row.hardware_reader_cycles for row in rows],
    )
    compute_round, compute_request, compute_simulator = (
        _fit_nonnegative_feature_model(
            [
                (
                    float(row.rounds),
                    row.simulator_compute_memory_requests,
                    row.simulator_compute_cycles,
                )
                for row in rows
            ],
            [row.hardware_compute_cycles for row in rows],
        )
    )
    span_residual = _fit_nonnegative_feature_model(
        [(float(row.rounds),) for row in rows],
        [
            row.hardware_iterative_span_cycles
            - max(row.hardware_reader_cycles, row.hardware_compute_cycles)
            for row in rows
        ],
    )[0]
    return SpineComponentFeatureModel(
        algorithm=algorithm,
        profile_id=profile_id,
        calibration_datasets=tuple(sorted(row.dataset for row in rows)),
        maintenance_fixed_cycles=maintenance_fixed,
        maintenance_simulator_scale=maintenance_scale,
        reader_memory_request_cycles=reader_request,
        reader_simulator_cycle_scale=reader_simulator,
        compute_round_cycles=compute_round,
        compute_memory_request_cycles=compute_request,
        compute_simulator_cycle_scale=compute_simulator,
        span_residual_cycles_per_round=span_residual,
    )


def spine_component_feature_prediction_rows(
    records: Iterable[SpineComponentFeatureRecord],
    model: SpineComponentFeatureModel,
) -> list[dict[str, object]]:
    """Apply a frozen component-feature model without fitting its input rows."""

    predictions: list[dict[str, object]] = []
    for record in records:
        if (record.algorithm, record.profile_id) != (
            model.algorithm,
            model.profile_id,
        ):
            raise ValueError("component-feature record/model identity mismatch")
        predicted = model.predict_components(
            rounds=record.rounds,
            simulator_maintenance_cycles=record.simulator_maintenance_cycles,
            simulator_reader_cycles=record.simulator_reader_cycles,
            simulator_compute_cycles=record.simulator_compute_cycles,
            simulator_reader_memory_requests=(
                record.simulator_reader_memory_requests
            ),
            simulator_compute_memory_requests=(
                record.simulator_compute_memory_requests
            ),
        )
        hardware_total = (
            record.hardware_maintenance_cycles
            + record.hardware_iterative_span_cycles
        )
        predictions.append(
            {
                **asdict(record),
                "predicted_maintenance_cycles": predicted["maintenance_cycles"],
                "maintenance_absolute_error_percent": absolute_error_percent(
                    predicted["maintenance_cycles"],
                    record.hardware_maintenance_cycles,
                ),
                "predicted_reader_cycles": predicted["reader_cycles"],
                "reader_absolute_error_percent": (
                    absolute_error_percent(
                        predicted["reader_cycles"], record.hardware_reader_cycles
                    )
                    if record.rounds
                    else 0.0
                ),
                "predicted_compute_cycles": predicted["compute_cycles"],
                "compute_absolute_error_percent": (
                    absolute_error_percent(
                        predicted["compute_cycles"], record.hardware_compute_cycles
                    )
                    if record.rounds
                    else 0.0
                ),
                "predicted_iterative_span_cycles": predicted[
                    "iterative_span_cycles"
                ],
                "iterative_span_absolute_error_percent": (
                    absolute_error_percent(
                        predicted["iterative_span_cycles"],
                        record.hardware_iterative_span_cycles,
                    )
                    if record.rounds
                    else 0.0
                ),
                "hardware_total_cycles": hardware_total,
                "predicted_total_cycles": predicted["total_cycles"],
                "total_absolute_error_percent": absolute_error_percent(
                    predicted["total_cycles"], hardware_total
                ),
            }
        )
    return predictions


def spine_component_feature_leave_one_dataset_out_rows(
    records: Iterable[SpineComponentFeatureRecord],
) -> list[dict[str, object]]:
    """Measure development-set transfer without changing the feature form."""

    rows = tuple(records)
    if len(rows) < 5:
        raise ValueError("leave-one-out validation requires at least five rows")
    predictions: list[dict[str, object]] = []
    for held_out in rows:
        training = tuple(row for row in rows if row.dataset != held_out.dataset)
        model = fit_spine_component_feature_model(training)
        prediction = spine_component_feature_prediction_rows((held_out,), model)[0]
        prediction["held_out_dataset"] = held_out.dataset
        prediction["training_datasets"] = ";".join(model.calibration_datasets)
        predictions.append(prediction)
    return predictions


def fit_spine_mechanism_component_model(
    records: Iterable[SpineMechanismComponentRecord],
    *,
    compute_strategy: str = "execution_span",
) -> SpineMechanismComponentModel:
    """Fit one immutable HLS mechanism model from calibration rows only."""

    rows = tuple(records)
    if len(rows) < 4:
        raise ValueError("mechanism-component freeze requires four calibration rows")
    if any(row.role != "calibration" for row in rows):
        raise ValueError("mechanism-component freeze rejects non-calibration rows")
    identities = {(row.algorithm, row.profile_id) for row in rows}
    if len(identities) != 1:
        raise ValueError("mechanism-component fit requires one algorithm/profile")
    if len({row.dataset for row in rows}) != len(rows):
        raise ValueError("mechanism-component fit requires distinct datasets")
    algorithm, profile_id = next(iter(identities))
    if compute_strategy not in {
        "execution_span",
        "fixed_plus_execution",
        "request_plus_execution",
    }:
        raise ValueError(f"unsupported compute strategy: {compute_strategy!r}")

    for row in rows:
        _require_positive_finite(row.vertices, "vertices")
        _require_positive_finite(
            row.simulator_maintenance_cycles, "simulator_maintenance_cycles"
        )
        _require_positive_finite(
            row.hardware_maintenance_cycles, "hardware_maintenance_cycles"
        )
        if row.rounds < 0:
            raise ValueError("rounds must be non-negative")

    maintenance_fixed, maintenance_scale = _fit_nonnegative_feature_model(
        [(1.0, row.simulator_maintenance_cycles) for row in rows],
        [row.hardware_maintenance_cycles for row in rows],
    )
    zero_round = all(row.rounds == 0 for row in rows)
    if zero_round:
        for row in rows:
            if any(
                value != 0
                for value in (
                    row.simulator_reader_cycles,
                    row.simulator_compute_cycles,
                    row.simulator_reader_memory_requests,
                    row.simulator_compute_memory_requests,
                    row.hardware_reader_cycles,
                    row.hardware_compute_cycles,
                    row.hardware_iterative_span_cycles,
                )
            ):
                raise ValueError("zero-round calibration contains iterative work")
        return SpineMechanismComponentModel(
            algorithm=algorithm,
            profile_id=profile_id,
            calibration_datasets=tuple(sorted(row.dataset for row in rows)),
            maintenance_fixed_cycles=maintenance_fixed,
            maintenance_simulator_scale=maintenance_scale,
            reader_round_cycles=0.0,
            reader_vertex_cycles=0.0,
            reader_memory_request_cycles=0.0,
            compute_fixed_cycles=0.0,
            compute_round_cycles=0.0,
            compute_memory_request_cycles=0.0,
            compute_simulator_cycle_scale=0.0,
            compute_strategy=compute_strategy,
            span_residual_cycles_per_round=0.0,
        )
    if any(row.rounds <= 0 for row in rows):
        raise ValueError("iterative calibration cannot mix zero and positive rounds")

    for row in rows:
        for value, name in (
            (row.simulator_reader_cycles, "simulator_reader_cycles"),
            (row.simulator_compute_cycles, "simulator_compute_cycles"),
            (
                row.simulator_reader_memory_requests,
                "simulator_reader_memory_requests",
            ),
            (
                row.simulator_compute_memory_requests,
                "simulator_compute_memory_requests",
            ),
            (row.hardware_reader_cycles, "hardware_reader_cycles"),
            (row.hardware_compute_cycles, "hardware_compute_cycles"),
            (
                row.hardware_iterative_span_cycles,
                "hardware_iterative_span_cycles",
            ),
        ):
            _require_positive_finite(value, name)
        if row.hardware_iterative_span_cycles < max(
            row.hardware_reader_cycles, row.hardware_compute_cycles
        ):
            raise ValueError("hardware span cannot be shorter than its components")

    reader_round, reader_vertex, reader_request = _fit_nonnegative_feature_model(
        [
            (
                float(row.rounds),
                row.vertices,
                row.simulator_reader_memory_requests,
            )
            for row in rows
        ],
        [row.hardware_reader_cycles for row in rows],
    )
    compute_fixed = 0.0
    compute_request = 0.0
    if compute_strategy == "execution_span":
        compute_round, compute_simulator = _fit_nonnegative_feature_model(
            [
                (float(row.rounds), row.simulator_compute_cycles)
                for row in rows
            ],
            [row.hardware_compute_cycles for row in rows],
        )
    elif compute_strategy == "fixed_plus_execution":
        compute_fixed, compute_simulator = _fit_nonnegative_feature_model(
            [
                (1.0, row.simulator_compute_cycles)
                for row in rows
            ],
            [row.hardware_compute_cycles for row in rows],
        )
        compute_round = 0.0
    else:
        compute_round, compute_request, compute_simulator = (
            _fit_nonnegative_feature_model(
                [
                    (
                        float(row.rounds),
                        row.simulator_compute_memory_requests,
                        row.simulator_compute_cycles,
                    )
                    for row in rows
                ],
                [row.hardware_compute_cycles for row in rows],
            )
        )
    span_residual = _fit_nonnegative_feature_model(
        [(float(row.rounds),) for row in rows],
        [
            row.hardware_iterative_span_cycles
            - max(row.hardware_reader_cycles, row.hardware_compute_cycles)
            for row in rows
        ],
    )[0]
    return SpineMechanismComponentModel(
        algorithm=algorithm,
        profile_id=profile_id,
        calibration_datasets=tuple(sorted(row.dataset for row in rows)),
        maintenance_fixed_cycles=maintenance_fixed,
        maintenance_simulator_scale=maintenance_scale,
        reader_round_cycles=reader_round,
        reader_vertex_cycles=reader_vertex,
        reader_memory_request_cycles=reader_request,
        compute_fixed_cycles=compute_fixed,
        compute_round_cycles=compute_round,
        compute_memory_request_cycles=compute_request,
        compute_simulator_cycle_scale=compute_simulator,
        compute_strategy=compute_strategy,
        span_residual_cycles_per_round=span_residual,
    )


def spine_mechanism_component_prediction_rows(
    records: Iterable[SpineMechanismComponentRecord],
    model: SpineMechanismComponentModel,
) -> list[dict[str, object]]:
    """Apply a frozen mechanism model without fitting its input rows."""

    predictions: list[dict[str, object]] = []
    for record in records:
        if (record.algorithm, record.profile_id) != (
            model.algorithm,
            model.profile_id,
        ):
            raise ValueError("mechanism-component record/model identity mismatch")
        predicted = model.predict_components(
            rounds=record.rounds,
            vertices=record.vertices,
            simulator_maintenance_cycles=record.simulator_maintenance_cycles,
            simulator_reader_cycles=record.simulator_reader_cycles,
            simulator_compute_cycles=record.simulator_compute_cycles,
            simulator_reader_memory_requests=(
                record.simulator_reader_memory_requests
            ),
            simulator_compute_memory_requests=(
                record.simulator_compute_memory_requests
            ),
        )
        hardware_total = (
            record.hardware_maintenance_cycles
            + record.hardware_iterative_span_cycles
        )
        row = {
            **asdict(record),
            "predicted_maintenance_cycles": predicted["maintenance_cycles"],
            "predicted_reader_cycles": predicted["reader_cycles"],
            "predicted_compute_cycles": predicted["compute_cycles"],
            "predicted_iterative_span_cycles": predicted["iterative_span_cycles"],
            "hardware_total_cycles": hardware_total,
            "predicted_total_cycles": predicted["total_cycles"],
            "maintenance_absolute_error_percent": absolute_error_percent(
                predicted["maintenance_cycles"], record.hardware_maintenance_cycles
            ),
            "reader_absolute_error_percent": 0.0,
            "compute_absolute_error_percent": 0.0,
            "iterative_span_absolute_error_percent": 0.0,
            "total_absolute_error_percent": absolute_error_percent(
                predicted["total_cycles"], hardware_total
            ),
        }
        if record.rounds:
            row["reader_absolute_error_percent"] = absolute_error_percent(
                predicted["reader_cycles"], record.hardware_reader_cycles
            )
            row["compute_absolute_error_percent"] = absolute_error_percent(
                predicted["compute_cycles"], record.hardware_compute_cycles
            )
            row["iterative_span_absolute_error_percent"] = absolute_error_percent(
                predicted["iterative_span_cycles"],
                record.hardware_iterative_span_cycles,
            )
        predictions.append(row)
    return predictions


def spine_mechanism_component_leave_one_dataset_out_rows(
    records: Iterable[SpineMechanismComponentRecord],
    *,
    compute_strategy: str = "execution_span",
) -> list[dict[str, object]]:
    """Measure development transfer without changing the mechanism form."""

    rows = tuple(records)
    if len(rows) < 5:
        raise ValueError("leave-one-out validation requires at least five rows")
    predictions: list[dict[str, object]] = []
    for held_out in rows:
        training = tuple(row for row in rows if row.dataset != held_out.dataset)
        model = fit_spine_mechanism_component_model(
            training, compute_strategy=compute_strategy
        )
        prediction = spine_mechanism_component_prediction_rows(
            (held_out,), model
        )[0]
        prediction["held_out_dataset"] = held_out.dataset
        prediction["training_datasets"] = ";".join(model.calibration_datasets)
        predictions.append(prediction)
    return predictions


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
            (row.simulator_vertices, "simulator_vertices"),
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
            (row.simulator_reader_range_tasks, "simulator_reader_range_tasks"),
            (
                row.simulator_reader_credit_stall_cycles,
                "simulator_reader_credit_stall_cycles",
            ),
            (
                row.simulator_compute_active_scan_words,
                "simulator_compute_active_scan_words",
            ),
            (row.simulator_compute_range_tasks, "simulator_compute_range_tasks"),
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
    reader_request_cycles, reader_round_cycles, reader_vertex_cycles = (
        _fit_nonnegative_feature_model(
            [
                (
                    row.simulator_reader_memory_requests,
                    float(row.iterations),
                    row.simulator_vertices,
                )
                for row in calibration
            ],
            [row.hardware_reader_cycles for row in calibration],
        )
    )
    compute_round_cycles, compute_task_cycles, compute_edge_cycles = (
        _fit_nonnegative_feature_model(
            [
                (
                    float(row.iterations),
                    row.simulator_compute_range_tasks,
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
        reader_memory_request_cycles=reader_request_cycles,
        reader_round_cycles=reader_round_cycles,
        reader_vertex_cycles=reader_vertex_cycles,
        compute_round_cycles=compute_round_cycles,
        compute_range_task_cycles=compute_task_cycles,
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
            simulator_vertices=record.simulator_vertices,
            simulator_maintenance_cycles=record.simulator_maintenance_cycles,
            simulator_reader_cycles=record.simulator_reader_cycles,
            simulator_compute_cycles=record.simulator_compute_cycles,
            simulator_reader_memory_requests=(
                record.simulator_reader_memory_requests
            ),
            simulator_reader_level_cache_words=(
                record.simulator_reader_level_cache_words
            ),
            simulator_reader_range_tasks=record.simulator_reader_range_tasks,
            simulator_reader_credit_stall_cycles=(
                record.simulator_reader_credit_stall_cycles
            ),
            simulator_compute_active_scan_words=(
                record.simulator_compute_active_scan_words
            ),
            simulator_compute_range_tasks=record.simulator_compute_range_tasks,
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


def overlap_leave_one_dataset_out_rows(
    records: Iterable[CurrentFPGAOverlapRecord],
) -> list[dict[str, object]]:
    """Predict each development dataset using a model fit without that dataset.

    This is development validation, not holdout evidence.  It checks whether a
    frozen feature form transfers across the calibration topologies before the
    independently hashed holdout workloads are executed.
    """

    calibration = tuple(row for row in records if row.role == "calibration")
    if len(calibration) < 5:
        raise ValueError("leave-one-dataset-out validation requires five calibration rows")
    datasets = [row.dataset for row in calibration]
    if len(set(datasets)) != len(datasets):
        raise ValueError("leave-one-dataset-out validation requires one row per dataset")

    rows: list[dict[str, object]] = []
    for held_out in calibration:
        training = tuple(row for row in calibration if row.dataset != held_out.dataset)
        validation = replace(held_out, role="development_validation")
        model = fit_overlap_timing_model((*training, validation))
        prediction = overlap_prediction_rows((validation,), model)[0]
        prediction["role"] = "leave_one_out"
        prediction["held_out_dataset"] = held_out.dataset
        prediction["training_datasets"] = ";".join(model.calibration_datasets)
        rows.append(prediction)
    return rows


def fit_overlap_v6_timing_model(
    records: Iterable[CurrentFPGAOverlapV6Record],
) -> OverlapTimingV6Model:
    """Fit the frozen cross-batch HLS-work model using calibration rows only."""

    rows = tuple(records)
    if not rows:
        raise ValueError("overlap-v6 timing calibration requires records")
    identities = {(row.architecture, row.algorithm, row.profile_id) for row in rows}
    if len(identities) != 1:
        raise ValueError("overlap-v6 fit requires one architecture/algorithm/profile")
    for row in rows:
        _validate_composed_role(row.role)
        if row.iterations <= 0:
            raise ValueError("overlap-v6 records require at least one iteration")
        for value, name in (
            (row.simulator_vertices, "simulator_vertices"),
            (row.simulator_maintenance_cycles, "simulator_maintenance_cycles"),
            (row.simulator_reader_cycles, "simulator_reader_cycles"),
            (row.simulator_compute_cycles, "simulator_compute_cycles"),
            (row.hardware_maintenance_cycles, "hardware_maintenance_cycles"),
            (row.hardware_reader_cycles, "hardware_reader_cycles"),
            (row.hardware_compute_cycles, "hardware_compute_cycles"),
            (row.hardware_iterative_span_cycles, "hardware_iterative_span_cycles"),
        ):
            _require_positive_finite(value, name)
        for value, name in (
            (row.simulator_reader_memory_requests, "simulator_reader_memory_requests"),
            (row.simulator_reader_metadata_bytes, "simulator_reader_metadata_bytes"),
            (row.simulator_reader_source_requests, "simulator_reader_source_requests"),
            (row.simulator_compute_memory_requests, "simulator_compute_memory_requests"),
            (
                row.simulator_compute_sparse_store_scan_words,
                "simulator_compute_sparse_store_scan_words",
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
    if len(calibration) < 6:
        raise ValueError("overlap-v6 fit requires at least six calibration rows")
    if {row.dataset for row in calibration} & {row.dataset for row in validation}:
        raise ValueError("calibration and validation datasets overlap")

    maintenance_fixed, maintenance_scale = _fit_nonnegative_two_feature_model(
        [(1.0, row.simulator_maintenance_cycles) for row in calibration],
        [row.hardware_maintenance_cycles for row in calibration],
    )
    reader_terms = _fit_nonnegative_feature_model(
        [
            (
                float(row.iterations),
                row.simulator_reader_memory_requests,
                row.simulator_reader_metadata_bytes,
                row.simulator_vertices,
            )
            for row in calibration
        ],
        [row.hardware_reader_cycles for row in calibration],
    )
    compute_terms = _fit_nonnegative_feature_model(
        [
            (
                float(row.iterations),
                row.simulator_compute_memory_requests,
                row.simulator_compute_sparse_store_scan_words,
                row.simulator_processed_edges,
            )
            for row in calibration
        ],
        [row.hardware_compute_cycles for row in calibration],
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
    return OverlapTimingV6Model(
        architecture=architecture,
        algorithm=algorithm,
        calibration_datasets=tuple(sorted(row.dataset for row in calibration)),
        maintenance_fixed_cycles=maintenance_fixed,
        maintenance_scale=maintenance_scale,
        reader_round_cycles=reader_terms[0],
        reader_memory_request_cycles=reader_terms[1],
        reader_metadata_byte_cycles=reader_terms[2],
        reader_vertex_cycles=reader_terms[3],
        compute_round_cycles=compute_terms[0],
        compute_memory_request_cycles=compute_terms[1],
        compute_sparse_store_scan_word_cycles=compute_terms[2],
        compute_processed_edge_cycles=compute_terms[3],
        span_residual_cycles_per_iteration=span_residual,
    )


def overlap_v6_prediction_rows(
    records: Iterable[CurrentFPGAOverlapV6Record], model: OverlapTimingV6Model
) -> list[dict[str, object]]:
    """Apply a frozen overlap-v6 model without fitting validation rows."""

    rows: list[dict[str, object]] = []
    for record in records:
        if (record.architecture, record.algorithm) != (
            model.architecture,
            model.algorithm,
        ):
            raise ValueError("overlap-v6 model identity does not match record")
        prediction = model.predict_components(
            iterations=record.iterations,
            simulator_vertices=record.simulator_vertices,
            simulator_maintenance_cycles=record.simulator_maintenance_cycles,
            simulator_reader_cycles=record.simulator_reader_cycles,
            simulator_compute_cycles=record.simulator_compute_cycles,
            simulator_reader_memory_requests=record.simulator_reader_memory_requests,
            simulator_reader_metadata_bytes=record.simulator_reader_metadata_bytes,
            simulator_reader_source_requests=record.simulator_reader_source_requests,
            simulator_compute_memory_requests=record.simulator_compute_memory_requests,
            simulator_compute_sparse_store_scan_words=(
                record.simulator_compute_sparse_store_scan_words
            ),
            simulator_processed_edges=record.simulator_processed_edges,
        )
        hardware_total = (
            record.hardware_maintenance_cycles
            + record.hardware_iterative_span_cycles
        )
        row: dict[str, object] = {**asdict(record)}
        row["hardware_total_cycles"] = hardware_total
        for component, predicted in prediction.items():
            row[f"predicted_{component}"] = predicted
        for component in ("maintenance", "reader", "compute", "iterative_span"):
            row[f"{component}_absolute_error_percent"] = absolute_error_percent(
                prediction[f"{component}_cycles"],
                getattr(record, f"hardware_{component}_cycles"),
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
