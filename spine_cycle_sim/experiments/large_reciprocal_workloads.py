"""Large reciprocal projections and component-merge updates for real graphs."""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
from typing import Iterable

from .connected_components_workloads import (
    connected_components_labels,
    validate_reciprocal_snapshot,
)
from .deltahls_workloads import validate_reciprocal_graph, validate_reciprocal_update
from .shared_workloads import SliceGraph, SliceRecord


@dataclass(frozen=True)
class LargeReciprocalFixture:
    graph: SliceGraph
    updates: dict[int, SliceGraph]
    source_pairs_scanned: int
    selected_pairs: int


def _weight(left: int, right: int) -> int:
    return 1 + ((left * 131 + right * 17 + 73) % 31)


def ordered_reciprocal_projection(
    source: SliceGraph, *, target_records: int, case_id: str
) -> tuple[SliceGraph, int]:
    """Take ordered unique undirected pairs, compact IDs, and emit both directions."""

    if target_records <= 0 or target_records % 2:
        raise ValueError("target reciprocal record count must be positive and even")
    target_pairs = target_records // 2
    selected: list[tuple[int, int]] = []
    seen: set[tuple[int, int]] = set()
    scanned = 0
    for edge in source.records:
        scanned += 1
        if edge.diff != 1 or edge.src == edge.dst:
            continue
        pair = (
            (edge.src, edge.dst)
            if edge.src < edge.dst
            else (edge.dst, edge.src)
        )
        if pair in seen:
            continue
        seen.add(pair)
        selected.append(pair)
        if len(selected) == target_pairs:
            break
    if len(selected) != target_pairs:
        raise ValueError("source does not contain enough unique undirected pairs")

    active_vertices = sorted({vertex for pair in selected for vertex in pair})
    compact = {vertex: index for index, vertex in enumerate(active_vertices)}
    records: list[SliceRecord] = []
    for old_left, old_right in selected:
        left, right = compact[old_left], compact[old_right]
        weight = _weight(left, right)
        records.extend(
            (SliceRecord(left, right, weight, 1), SliceRecord(right, left, weight, 1))
        )
    graph = SliceGraph(case_id, len(active_vertices), tuple(sorted(records)))
    validate_reciprocal_graph(graph)
    validate_reciprocal_snapshot(graph)
    return graph, scanned


def component_bridge_batches(
    graph: SliceGraph,
    batch_sizes: Iterable[int],
    *,
    case_prefix: str,
) -> dict[int, SliceGraph]:
    """Create nested inserts that merge the minimum-label component with others."""

    sizes = tuple(sorted(set(batch_sizes)))
    if not sizes or sizes[0] <= 0:
        raise ValueError("component bridge batch sizes must be positive")
    labels = connected_components_labels(graph)
    component_sizes = Counter(labels)
    anchor_label = labels[0]
    candidates = sorted(
        (label for label in component_sizes if label != anchor_label),
        key=lambda label: (-component_sizes[label], label),
    )
    if len(candidates) < sizes[-1]:
        raise ValueError("graph has too few components for requested bridge batches")
    existing = {(edge.src, edge.dst) for edge in graph.records}
    selected: list[tuple[int, int]] = []
    for representative in candidates:
        pair = (0, representative)
        if pair not in existing and (pair[1], pair[0]) not in existing:
            selected.append(pair)
        if len(selected) == sizes[-1]:
            break
    if len(selected) != sizes[-1]:
        raise ValueError("could not find enough absent cross-component bridges")

    batches: dict[int, SliceGraph] = {}
    for size in sizes:
        records: list[SliceRecord] = []
        for left, right in selected[:size]:
            weight = _weight(left, right)
            records.extend(
                (
                    SliceRecord(left, right, weight, 1),
                    SliceRecord(right, left, weight, 1),
                )
            )
        update = SliceGraph(
            f"{case_prefix}_insert_bridge_u{size}",
            graph.vertices,
            tuple(sorted(records)),
        )
        validate_reciprocal_update(graph, update)
        batches[size] = update
    return batches


def build_large_reciprocal_fixture(
    source: SliceGraph,
    *,
    target_records: int = 540_000,
    batch_sizes: Iterable[int] = (1, 8, 64, 512),
    case_prefix: str = "askubuntu_reciprocal_gate",
) -> LargeReciprocalFixture:
    graph, scanned = ordered_reciprocal_projection(
        source,
        target_records=target_records,
        case_id=f"{case_prefix}_e{target_records}",
    )
    updates = component_bridge_batches(
        graph,
        batch_sizes,
        case_prefix=graph.case_id,
    )
    return LargeReciprocalFixture(
        graph=graph,
        updates=updates,
        source_pairs_scanned=scanned,
        selected_pairs=target_records // 2,
    )
