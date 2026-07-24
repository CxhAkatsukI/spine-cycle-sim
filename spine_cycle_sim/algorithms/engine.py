"""Shared Map/Reduce/Apply functional engine and algorithm policies."""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from enum import Enum
import math
import struct
from typing import Any, Iterable

from .graph import BatchEffect, DynamicGraph, EdgeUpdate


class NumericMode(str, Enum):
    FLOAT64 = "float64"
    FLOAT32 = "float32"


def quantize(value: float, mode: NumericMode) -> float:
    if mode == NumericMode.FLOAT64:
        return float(value)
    return struct.unpack("!f", struct.pack("!f", float(value)))[0]


@dataclass(frozen=True)
class AlgorithmConfig:
    source: int = 0
    damping: float = 0.85
    epsilon: float = 1e-6
    max_iterations: int = 100
    fixed_iterations: int | None = None

    def validate(self, vertices: int) -> None:
        if self.source < 0 or self.source >= vertices:
            raise ValueError("source is outside the graph")
        if not 0.0 < self.damping < 1.0:
            raise ValueError("damping must be in (0, 1)")
        if self.epsilon <= 0.0 or self.max_iterations <= 0:
            raise ValueError("epsilon and max_iterations must be positive")
        if self.fixed_iterations is not None and self.fixed_iterations <= 0:
            raise ValueError("fixed_iterations must be positive")


@dataclass
class AlgorithmState:
    values: list[int | float]
    residuals: list[float] = field(default_factory=list)
    active: set[int] = field(default_factory=set)


@dataclass(frozen=True)
class IterationResult:
    active: set[int]
    error: float
    applied_vertices: int


@dataclass(frozen=True)
class AlgorithmStats:
    iterations: int
    converged: bool
    mapped_edges: int
    reduced_updates: int
    applied_vertices: int
    active_vertices: int
    frontier_sizes: tuple[int, ...]
    final_error: float


@dataclass(frozen=True)
class AlgorithmResult:
    algorithm: str
    numeric_mode: NumericMode
    values: tuple[int | float, ...]
    residuals: tuple[float, ...]
    stats: AlgorithmStats


class DynamicExecutionMode(str, Enum):
    INCREMENTAL = "incremental"
    FULL_RECOMPUTE_FALLBACK = "full_recompute_fallback"
    WARM_START = "warm_start"
    SIGNED_RESIDUAL = "signed_residual"


@dataclass(frozen=True)
class PreparedUpdate:
    state: AlgorithmState
    mode: DynamicExecutionMode


@dataclass(frozen=True)
class DynamicBatchResult:
    batch_index: int
    effect: BatchEffect
    execution_mode: DynamicExecutionMode
    result: AlgorithmResult
    cold_reference: AlgorithmResult
    oracle_match: bool
    oracle_l1_difference: float
    oracle_max_abs_difference: float


@dataclass(frozen=True)
class DynamicRunResult:
    initial: AlgorithmResult
    batches: tuple[DynamicBatchResult, ...]

    @property
    def final(self) -> AlgorithmResult:
        return self.batches[-1].result if self.batches else self.initial


@dataclass(frozen=True)
class DynamicNumericComparison:
    batch_index: int
    exact_match: bool
    l1_difference: float
    max_abs_difference: float


@dataclass(frozen=True)
class DynamicDualOracleResult:
    mathematical: DynamicRunResult
    architecture: DynamicRunResult
    initial: DualOracleResult
    batches: tuple[DynamicNumericComparison, ...]


class AlgorithmPolicy(ABC):
    name: str

    @abstractmethod
    def initialize(
        self, graph: DynamicGraph, config: AlgorithmConfig, numeric: NumericMode
    ) -> AlgorithmState:
        raise NotImplementedError

    @abstractmethod
    def begin_iteration(
        self, graph: DynamicGraph, state: AlgorithmState,
        config: AlgorithmConfig, numeric: NumericMode
    ) -> Any:
        raise NotImplementedError

    @abstractmethod
    def sources(
        self, graph: DynamicGraph, state: AlgorithmState, context: Any
    ) -> Iterable[int]:
        raise NotImplementedError

    @abstractmethod
    def map_edge(
        self, src: int, dst: int, weight: int, graph: DynamicGraph,
        state: AlgorithmState, context: Any, config: AlgorithmConfig,
        numeric: NumericMode
    ) -> float | int:
        raise NotImplementedError

    @abstractmethod
    def reduce(
        self, current: float | int | None, candidate: float | int,
        numeric: NumericMode
    ) -> float | int:
        raise NotImplementedError

    @abstractmethod
    def apply(
        self, graph: DynamicGraph, state: AlgorithmState,
        reduced: dict[int, float | int], context: Any,
        config: AlgorithmConfig, numeric: NumericMode
    ) -> IterationResult:
        raise NotImplementedError

    @abstractmethod
    def converged(self, result: IterationResult, config: AlgorithmConfig) -> bool:
        raise NotImplementedError

    @abstractmethod
    def prepare_update(
        self,
        graph: DynamicGraph,
        previous: AlgorithmResult,
        effect: BatchEffect,
        config: AlgorithmConfig,
        numeric: NumericMode,
    ) -> PreparedUpdate:
        raise NotImplementedError


class MapReduceEngine:
    def run(
        self,
        graph: DynamicGraph,
        policy: AlgorithmPolicy,
        config: AlgorithmConfig,
        numeric: NumericMode,
        initial_state: AlgorithmState | None = None,
    ) -> AlgorithmResult:
        config.validate(graph.vertices)
        initialized = initial_state or policy.initialize(graph, config, numeric)
        if len(initialized.values) != graph.vertices or (
            initialized.residuals and len(initialized.residuals) != graph.vertices
        ):
            raise ValueError("algorithm state does not match graph size")
        state = AlgorithmState(
            values=list(initialized.values),
            residuals=list(initialized.residuals),
            active=set(initialized.active),
        )
        mapped_edges = reduced_updates = applied_vertices = active_vertices = 0
        frontier_sizes: list[int] = []
        converged = False
        final_error = math.inf
        limit = config.fixed_iterations or config.max_iterations

        for iteration in range(limit):
            context = policy.begin_iteration(graph, state, config, numeric)
            sources = tuple(policy.sources(graph, state, context))
            frontier_sizes.append(len(sources))
            active_vertices += len(sources)
            reduced: dict[int, float | int] = {}
            for src in sources:
                for dst, weight in graph.out_edges(src):
                    candidate = policy.map_edge(
                        src, dst, weight, graph, state, context, config, numeric
                    )
                    reduced[dst] = policy.reduce(reduced.get(dst), candidate, numeric)
                    mapped_edges += 1
                    reduced_updates += 1
            result = policy.apply(
                graph, state, reduced, context, config, numeric
            )
            applied_vertices += result.applied_vertices
            final_error = result.error
            state.active = result.active
            if config.fixed_iterations is None and policy.converged(result, config):
                converged = True
                iterations = iteration + 1
                break
        else:
            iterations = limit
            if config.fixed_iterations is not None:
                converged = policy.converged(
                    IterationResult(state.active, final_error, 0), config
                )

        return AlgorithmResult(
            algorithm=policy.name,
            numeric_mode=numeric,
            values=tuple(state.values),
            residuals=tuple(state.residuals),
            stats=AlgorithmStats(
                iterations=iterations,
                converged=converged,
                mapped_edges=mapped_edges,
                reduced_updates=reduced_updates,
                applied_vertices=applied_vertices,
                active_vertices=active_vertices,
                frontier_sizes=tuple(frontier_sizes),
                final_error=final_error,
            ),
        )


class WeightedSsspPolicy(AlgorithmPolicy):
    name = "sssp"
    infinity = (1 << 63) - 1
    architecture_infinity = (1 << 32) - 1

    def limit(self, numeric: NumericMode) -> int:
        return (
            self.infinity
            if numeric == NumericMode.FLOAT64
            else self.architecture_infinity
        )

    def initialize(self, graph, config, numeric):
        values = [self.limit(numeric)] * graph.vertices
        values[config.source] = 0
        return AlgorithmState(values=values, active={config.source})

    def begin_iteration(self, graph, state, config, numeric):
        return None

    def sources(self, graph, state, context):
        return sorted(state.active)

    def map_edge(self, src, dst, weight, graph, state, context, config, numeric):
        return min(self.limit(numeric), int(state.values[src]) + weight)

    def reduce(self, current, candidate, numeric):
        return candidate if current is None else min(current, candidate)

    def apply(self, graph, state, reduced, context, config, numeric):
        active: set[int] = set()
        for vertex, candidate in reduced.items():
            if candidate < state.values[vertex]:
                state.values[vertex] = int(candidate)
                active.add(vertex)
        return IterationResult(
            active=active,
            error=float(len(active)),
            applied_vertices=len(reduced),
        )

    def converged(self, result, config):
        return not result.active

    def prepare_update(self, graph, previous, effect, config, numeric):
        if effect.deleted or effect.increased:
            return PreparedUpdate(
                self.initialize(graph, config, numeric),
                DynamicExecutionMode.FULL_RECOMPUTE_FALLBACK,
            )
        return PreparedUpdate(
            AlgorithmState(
                values=list(previous.values),
                active=set(effect.changed_sources),
            ),
            DynamicExecutionMode.INCREMENTAL,
        )


class FullPageRankPolicy(AlgorithmPolicy):
    name = "full_pagerank"

    def initialize(self, graph, config, numeric):
        initial = quantize(1.0 / graph.vertices, numeric)
        return AlgorithmState(values=[initial] * graph.vertices, active=set(range(graph.vertices)))

    def begin_iteration(self, graph, state, config, numeric):
        dangling = quantize(
            sum(float(state.values[v]) for v in range(graph.vertices) if graph.out_degree(v) == 0),
            numeric,
        )
        return {"dangling": dangling}

    def sources(self, graph, state, context):
        return range(graph.vertices)

    def map_edge(self, src, dst, weight, graph, state, context, config, numeric):
        share = quantize(float(state.values[src]) / graph.out_degree(src), numeric)
        return quantize(config.damping * share, numeric)

    def reduce(self, current, candidate, numeric):
        return candidate if current is None else quantize(float(current) + float(candidate), numeric)

    def apply(self, graph, state, reduced, context, config, numeric):
        base = quantize((1.0 - config.damping) / graph.vertices, numeric)
        dangling = quantize(
            config.damping * context["dangling"] / graph.vertices, numeric
        )
        new_values: list[float] = []
        error = 0.0
        for vertex in range(graph.vertices):
            value = quantize(base + dangling, numeric)
            value = quantize(value + float(reduced.get(vertex, 0.0)), numeric)
            error += abs(value - float(state.values[vertex]))
            new_values.append(value)
        state.values = new_values
        return IterationResult(
            active=set(range(graph.vertices)),
            error=error,
            applied_vertices=graph.vertices,
        )

    def converged(self, result, config):
        return result.error <= config.epsilon

    def prepare_update(self, graph, previous, effect, config, numeric):
        del effect, config
        return PreparedUpdate(
            AlgorithmState(
                values=[quantize(float(value), numeric) for value in previous.values],
                active=set(range(graph.vertices)),
            ),
            DynamicExecutionMode.WARM_START,
        )


class ResidualPageRankPolicy(AlgorithmPolicy):
    name = "residual_pagerank"

    def initialize(self, graph, config, numeric):
        initial_residual = quantize((1.0 - config.damping) / graph.vertices, numeric)
        return AlgorithmState(
            values=[quantize(0.0, numeric)] * graph.vertices,
            residuals=[initial_residual] * graph.vertices,
            active=set(range(graph.vertices)),
        )

    def begin_iteration(self, graph, state, config, numeric):
        deltas: dict[int, float] = {}
        dangling = 0.0
        for vertex in sorted(state.active):
            delta = state.residuals[vertex]
            deltas[vertex] = delta
            state.residuals[vertex] = quantize(0.0, numeric)
            state.values[vertex] = quantize(float(state.values[vertex]) + delta, numeric)
            if graph.out_degree(vertex) == 0:
                dangling = quantize(dangling + delta, numeric)
        return {"deltas": deltas, "dangling": dangling}

    def sources(self, graph, state, context):
        return sorted(context["deltas"])

    def map_edge(self, src, dst, weight, graph, state, context, config, numeric):
        share = quantize(context["deltas"][src] / graph.out_degree(src), numeric)
        return quantize(config.damping * share, numeric)

    def reduce(self, current, candidate, numeric):
        return candidate if current is None else quantize(float(current) + float(candidate), numeric)

    def apply(self, graph, state, reduced, context, config, numeric):
        dangling = quantize(
            config.damping * context["dangling"] / graph.vertices, numeric
        )
        active: set[int] = set()
        error = 0.0
        threshold = config.epsilon / graph.vertices
        for vertex in range(graph.vertices):
            incoming = quantize(float(reduced.get(vertex, 0.0)) + dangling, numeric)
            state.residuals[vertex] = quantize(
                state.residuals[vertex] + incoming, numeric
            )
            error += abs(state.residuals[vertex])
            if abs(state.residuals[vertex]) > threshold:
                active.add(vertex)
        return IterationResult(
            active=active,
            error=error,
            applied_vertices=graph.vertices,
        )

    def converged(self, result, config):
        return not result.active

    def prepare_update(self, graph, previous, effect, config, numeric):
        del effect
        ranks = [quantize(float(value), numeric) for value in previous.values]
        dangling_mass = quantize(
            sum(
                ranks[vertex]
                for vertex in range(graph.vertices)
                if graph.out_degree(vertex) == 0
            ),
            numeric,
        )
        base = quantize((1.0 - config.damping) / graph.vertices, numeric)
        dangling = quantize(
            config.damping * dangling_mass / graph.vertices, numeric
        )
        targets = [quantize(base + dangling, numeric) for _ in range(graph.vertices)]
        for src in range(graph.vertices):
            degree = graph.out_degree(src)
            if degree == 0:
                continue
            share = quantize(ranks[src] / degree, numeric)
            candidate = quantize(config.damping * share, numeric)
            for dst, _weight in graph.out_edges(src):
                targets[dst] = quantize(targets[dst] + candidate, numeric)
        residuals = [
            quantize(target - rank, numeric)
            for target, rank in zip(targets, ranks, strict=True)
        ]
        threshold = config.epsilon / graph.vertices
        active = {
            vertex
            for vertex, residual in enumerate(residuals)
            if abs(residual) > threshold
        }
        return PreparedUpdate(
            AlgorithmState(values=ranks, residuals=residuals, active=active),
            DynamicExecutionMode.SIGNED_RESIDUAL,
        )


@dataclass(frozen=True)
class DualOracleResult:
    mathematical: AlgorithmResult
    architecture: AlgorithmResult
    exact_match: bool
    l1_difference: float
    max_abs_difference: float


def _numeric_differences(
    policy: AlgorithmPolicy,
    mathematical: AlgorithmResult,
    architecture: AlgorithmResult,
) -> tuple[bool, list[float]]:
    pairs = list(zip(mathematical.values, architecture.values, strict=True))
    if isinstance(policy, WeightedSsspPolicy):
        equivalent = [
            left == right
            or (
                left == policy.infinity
                and right == policy.architecture_infinity
            )
            for left, right in pairs
        ]
        return all(equivalent), [
            0.0 if same else abs(float(left) - float(right))
            for (left, right), same in zip(pairs, equivalent, strict=True)
        ]
    differences = [abs(float(left) - float(right)) for left, right in pairs]
    return mathematical.values == architecture.values, differences


def _oracle_comparison(
    policy: AlgorithmPolicy,
    result: AlgorithmResult,
    reference: AlgorithmResult,
    config: AlgorithmConfig,
    numeric: NumericMode,
) -> tuple[bool, float, float]:
    if isinstance(policy, WeightedSsspPolicy):
        exact, differences = _numeric_differences(policy, result, reference)
        return exact, sum(differences), max(differences, default=0.0)
    differences = [
        abs(float(left) - float(right))
        for left, right in zip(result.values, reference.values, strict=True)
    ]
    l1 = sum(differences)
    maximum = max(differences, default=0.0)
    floor = 2e-5 if numeric == NumericMode.FLOAT32 else 1e-12
    tolerance = max(config.epsilon * 8.0, floor)
    return maximum <= tolerance and l1 <= tolerance * len(differences), l1, maximum


def run_dual_oracle(
    graph: DynamicGraph, policy: AlgorithmPolicy, config: AlgorithmConfig
) -> DualOracleResult:
    engine = MapReduceEngine()
    mathematical = engine.run(graph, policy, config, NumericMode.FLOAT64)
    architecture = engine.run(graph, policy, config, NumericMode.FLOAT32)
    exact_match, differences = _numeric_differences(
        policy, mathematical, architecture
    )
    return DualOracleResult(
        mathematical=mathematical,
        architecture=architecture,
        exact_match=exact_match,
        l1_difference=sum(differences),
        max_abs_difference=max(differences, default=0.0),
    )


def run_dynamic_batches(
    graph: DynamicGraph,
    batches: Iterable[Iterable[EdgeUpdate]],
    policy: AlgorithmPolicy,
    config: AlgorithmConfig,
    numeric: NumericMode,
) -> DynamicRunResult:
    working = graph.clone()
    engine = MapReduceEngine()
    initial = engine.run(working, policy, config, numeric)
    previous = initial
    batch_results: list[DynamicBatchResult] = []
    for batch_index, updates in enumerate(batches):
        effect = working.apply_batch(list(updates))
        prepared = policy.prepare_update(
            working, previous, effect, config, numeric
        )
        result = engine.run(
            working, policy, config, numeric, initial_state=prepared.state
        )
        reference = engine.run(working, policy, config, numeric)
        oracle_match, l1, maximum = _oracle_comparison(
            policy, result, reference, config, numeric
        )
        batch_results.append(
            DynamicBatchResult(
                batch_index=batch_index,
                effect=effect,
                execution_mode=prepared.mode,
                result=result,
                cold_reference=reference,
                oracle_match=oracle_match,
                oracle_l1_difference=l1,
                oracle_max_abs_difference=maximum,
            )
        )
        previous = result
    return DynamicRunResult(initial=initial, batches=tuple(batch_results))


def run_dynamic_dual_oracle(
    graph: DynamicGraph,
    batches: Iterable[Iterable[EdgeUpdate]],
    policy: AlgorithmPolicy,
    config: AlgorithmConfig,
) -> DynamicDualOracleResult:
    materialized = tuple(tuple(batch) for batch in batches)
    mathematical = run_dynamic_batches(
        graph, materialized, policy, config, NumericMode.FLOAT64
    )
    architecture = run_dynamic_batches(
        graph, materialized, policy, config, NumericMode.FLOAT32
    )
    initial = run_dual_oracle(graph, policy, config)
    comparisons: list[DynamicNumericComparison] = []
    for math_batch, arch_batch in zip(
        mathematical.batches, architecture.batches, strict=True
    ):
        exact, differences = _numeric_differences(
            policy, math_batch.result, arch_batch.result
        )
        comparisons.append(
            DynamicNumericComparison(
                batch_index=math_batch.batch_index,
                exact_match=exact,
                l1_difference=sum(differences),
                max_abs_difference=max(differences, default=0.0),
            )
        )
    return DynamicDualOracleResult(
        mathematical=mathematical,
        architecture=architecture,
        initial=initial,
        batches=tuple(comparisons),
    )
