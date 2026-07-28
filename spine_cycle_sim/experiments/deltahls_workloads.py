"""Deterministic sink-free reciprocal workloads for Delta.hls and CC."""

from __future__ import annotations

from dataclasses import dataclass
import random
from typing import Iterable

from .shared_workloads import SliceGraph, SliceRecord


DEFAULT_BATCH_SIZES = (1, 8, 64, 4096)
DEFAULT_CANDIDATE_SEED = 0xD311A


@dataclass(frozen=True)
class ReciprocalClosure:
    graph: SliceGraph
    original_records: int
    reciprocal_records_added: int
    self_loops: int


def _positive_edges(graph: SliceGraph) -> dict[tuple[int, int], int]:
    edges: dict[tuple[int, int], int] = {}
    for record in graph.records:
        if record.diff != 1:
            raise ValueError("base graph must contain positive records only")
        if not (0 <= record.src < graph.vertices and 0 <= record.dst < graph.vertices):
            raise ValueError("base graph record has an out-of-range vertex")
        key = (record.src, record.dst)
        previous = edges.setdefault(key, record.weight)
        if previous != record.weight:
            raise ValueError(f"conflicting duplicate edge weights for {key}")
    return edges


def reciprocal_closure(graph: SliceGraph, *, case_id: str) -> ReciprocalClosure:
    """Return a weighted reciprocal closure while preserving compact IDs."""

    original = _positive_edges(graph)
    closed = dict(original)
    for (source, destination), weight in original.items():
        reverse = (destination, source)
        reverse_weight = closed.setdefault(reverse, weight)
        if reverse_weight != weight:
            raise ValueError(
                f"reciprocal edge weights disagree for {source}<->{destination}"
            )
    out_degree = [0] * graph.vertices
    for source, _ in closed:
        out_degree[source] += 1
    sinks = [vertex for vertex, degree in enumerate(out_degree) if degree == 0]
    if sinks:
        raise ValueError(f"reciprocal closure still has {len(sinks)} isolated vertices")
    records = tuple(
        SliceRecord(source, destination, weight, 1)
        for (source, destination), weight in sorted(closed.items())
    )
    return ReciprocalClosure(
        SliceGraph(case_id, graph.vertices, records),
        original_records=len(original),
        reciprocal_records_added=len(closed) - len(original),
        self_loops=sum(source == destination for source, destination in original),
    )


def _candidate_pairs(
    graph: SliceGraph, count: int, *, seed: int
) -> tuple[tuple[int, int], ...]:
    if count <= 0:
        raise ValueError("candidate count must be positive")
    if graph.vertices < 2:
        raise ValueError("at least two vertices are required")
    existing = {(record.src, record.dst) for record in graph.records}
    capacity = graph.vertices * (graph.vertices - 1) // 2
    occupied = sum(source < destination for source, destination in existing)
    if count > capacity - occupied:
        raise ValueError("not enough absent reciprocal pairs for requested batch")

    rng = random.Random(seed)
    selected: set[tuple[int, int]] = set()
    while len(selected) < count:
        left = rng.randrange(graph.vertices)
        right = rng.randrange(graph.vertices - 1)
        if right >= left:
            right += 1
        pair = (left, right) if left < right else (right, left)
        if pair in selected or pair in existing or (pair[1], pair[0]) in existing:
            continue
        selected.add(pair)
    return tuple(sorted(selected))


def _pair_weight(left: int, right: int) -> int:
    return 1 + ((left * 131 + right * 17 + 41) % 31)


def reciprocal_insert_batches(
    graph: SliceGraph,
    batch_sizes: Iterable[int] = DEFAULT_BATCH_SIZES,
    *,
    case_prefix: str,
    seed: int = DEFAULT_CANDIDATE_SEED,
) -> dict[int, SliceGraph]:
    """Create nested atomic reciprocal insertion batches."""

    sizes = tuple(sorted(set(batch_sizes)))
    if not sizes or sizes[0] <= 0:
        raise ValueError("batch sizes must be positive")
    pairs = _candidate_pairs(graph, sizes[-1], seed=seed)
    batches: dict[int, SliceGraph] = {}
    for size in sizes:
        records: list[SliceRecord] = []
        for left, right in pairs[:size]:
            weight = _pair_weight(left, right)
            records.append(SliceRecord(left, right, weight, 1))
            records.append(SliceRecord(right, left, weight, 1))
        batches[size] = SliceGraph(
            f"{case_prefix}_insert_u{size}", graph.vertices, tuple(sorted(records))
        )
    return batches


def validate_reciprocal_graph(graph: SliceGraph) -> None:
    edges = _positive_edges(graph)
    for (source, destination), weight in edges.items():
        if edges.get((destination, source)) != weight:
            raise ValueError(f"missing weighted reciprocal for {source}->{destination}")
    sources = {source for source, _ in edges}
    if len(sources) != graph.vertices:
        raise ValueError("reciprocal graph contains a sink or isolated vertex")


def validate_reciprocal_update(base: SliceGraph, update: SliceGraph) -> None:
    if base.vertices != update.vertices:
        raise ValueError("base and update vertex counts differ")
    validate_reciprocal_graph(base)
    base_edges = {(record.src, record.dst) for record in base.records}
    updates = _positive_edges(update)
    for (source, destination), weight in updates.items():
        if source == destination:
            raise ValueError("formal reciprocal updates exclude self loops")
        if (source, destination) in base_edges:
            raise ValueError("insert update already exists in the base graph")
        if updates.get((destination, source)) != weight:
            raise ValueError("insert update is not an atomic reciprocal pair")
