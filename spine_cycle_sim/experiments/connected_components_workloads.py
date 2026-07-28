"""Frozen reciprocal workloads and independent oracles for dynamic CC."""

from __future__ import annotations

from collections import Counter, deque
from dataclasses import dataclass
from typing import Iterable

from .shared_workloads import SliceGraph, SliceRecord


CC_BATCH_SIZES = (1, 8, 64, 4096)


@dataclass(frozen=True)
class ReciprocalUpdateAnalysis:
    logical_user_mutations: int
    effective_mutations: int
    physical_records: int
    insertions: int
    deletions: int
    zero_net: bool
    touched_vertices: tuple[int, ...]


@dataclass(frozen=True)
class ConnectedComponentsFixture:
    fixture_id: str
    workload_class: str
    role: str
    graph: SliceGraph
    update: SliceGraph


def _record_counts(
    graph: SliceGraph,
) -> Counter[tuple[int, int, int, int]]:
    counts: Counter[tuple[int, int, int, int]] = Counter()
    for edge in graph.records:
        if not (0 <= edge.src < graph.vertices and 0 <= edge.dst < graph.vertices):
            raise ValueError("connected-components edge is out of range")
        if edge.diff not in {-1, 1}:
            raise ValueError("connected-components records require unit signed diff")
        counts[(edge.src, edge.dst, edge.weight, edge.diff)] += 1
    return counts


def validate_reciprocal_snapshot(graph: SliceGraph) -> None:
    counts = _record_counts(graph)
    for (source, destination, weight, diff), count in counts.items():
        if diff != 1 or count != 1:
            raise ValueError("CC snapshot must be a simple positive graph")
        if counts[(destination, source, weight, 1)] != 1:
            raise ValueError("CC snapshot is missing a weighted reciprocal edge")


def analyze_reciprocal_update(
    graph: SliceGraph, update: SliceGraph
) -> ReciprocalUpdateAnalysis:
    if graph.vertices != update.vertices or not update.records:
        raise ValueError("CC update requires matching non-empty graphs")
    validate_reciprocal_snapshot(graph)
    base = {(edge.src, edge.dst, edge.weight) for edge in graph.records}
    counts = _record_counts(update)
    touched: set[int] = set()
    logical = 0
    insertions = 0
    deletions = 0
    net: Counter[tuple[int, int, int]] = Counter()
    for (source, destination, weight, diff), count in counts.items():
        if source == destination:
            raise ValueError("formal CC updates exclude self loops")
        if counts[(destination, source, weight, diff)] != count:
            raise ValueError("CC update is not an atomic reciprocal pair")
        if source < destination:
            logical += count
            if diff > 0:
                insertions += count
            else:
                deletions += count
        net[(source, destination, weight)] += diff * count
        touched.update((source, destination))

    effective = 0
    for (source, destination, weight), delta in net.items():
        reverse = net[(destination, source, weight)]
        if reverse != delta:
            raise ValueError("CC update has asymmetric net multiplicity")
        if source > destination or delta == 0:
            continue
        effective += abs(delta)
        exists = (source, destination, weight) in base
        if delta > 0 and exists:
            raise ValueError("CC insertion already exists in the base graph")
        if delta < 0 and not exists:
            raise ValueError("CC deletion is absent from the base graph")
        if abs(delta) != 1:
            raise ValueError("CC update changes an edge by more than one instance")
    return ReciprocalUpdateAnalysis(
        logical_user_mutations=logical,
        effective_mutations=effective,
        physical_records=len(update.records),
        insertions=insertions,
        deletions=deletions,
        zero_net=effective == 0,
        touched_vertices=tuple(sorted(touched)),
    )


def materialize_reciprocal_update(
    graph: SliceGraph, update: SliceGraph
) -> SliceGraph:
    analysis = analyze_reciprocal_update(graph, update)
    del analysis
    edges = Counter((edge.src, edge.dst, edge.weight) for edge in graph.records)
    for edge in update.records:
        key = (edge.src, edge.dst, edge.weight)
        edges[key] += edge.diff
        if edges[key] < 0:
            raise ValueError("CC update deletes a missing edge")
    records = tuple(
        SliceRecord(source, destination, weight, 1)
        for (source, destination, weight), count in sorted(edges.items())
        for _ in range(count)
    )
    result = SliceGraph(f"{graph.case_id}+{update.case_id}", graph.vertices, records)
    validate_reciprocal_snapshot(result)
    return result


def connected_components_labels(graph: SliceGraph) -> tuple[int, ...]:
    """Independent BFS oracle with minimum external vertex labels."""

    validate_reciprocal_snapshot(graph)
    adjacency: list[list[int]] = [[] for _ in range(graph.vertices)]
    for edge in graph.records:
        adjacency[edge.src].append(edge.dst)
    labels = [-1] * graph.vertices
    for root in range(graph.vertices):
        if labels[root] != -1:
            continue
        labels[root] = root
        pending = deque([root])
        while pending:
            source = pending.popleft()
            for destination in adjacency[source]:
                if labels[destination] == -1:
                    labels[destination] = root
                    pending.append(destination)
    return tuple(labels)


def _weight(left: int, right: int, salt: int) -> int:
    return 1 + ((left * 131 + right * 17 + salt * 29) % 31)


def _reciprocal_graph(
    case_id: str,
    vertices: int,
    pairs: Iterable[tuple[int, int]],
    *,
    salt: int,
) -> SliceGraph:
    records: list[SliceRecord] = []
    for left, right in pairs:
        weight = _weight(min(left, right), max(left, right), salt)
        records.extend(
            (SliceRecord(left, right, weight, 1), SliceRecord(right, left, weight, 1))
        )
    graph = SliceGraph(case_id, vertices, tuple(sorted(records)))
    validate_reciprocal_snapshot(graph)
    return graph


def _reciprocal_update(
    case_id: str,
    vertices: int,
    pairs: Iterable[tuple[int, int]],
    *,
    salt: int,
    diff: int,
) -> SliceGraph:
    records: list[SliceRecord] = []
    for left, right in pairs:
        weight = _weight(min(left, right), max(left, right), salt)
        records.extend(
            (SliceRecord(left, right, weight, diff), SliceRecord(right, left, weight, diff))
        )
    return SliceGraph(case_id, vertices, tuple(sorted(records)))


def formal_connected_components_fixtures() -> tuple[ConnectedComponentsFixture, ...]:
    """Return the frozen semantic and dense-stress CC fixture matrix."""

    fixtures: list[ConnectedComponentsFixture] = []
    definitions = (
        (
            "same_component_noop",
            8,
            ((0, 1), (1, 2), (4, 5)),
            ((0, 2),),
        ),
        (
            "small_component_merge",
            8,
            ((0, 1), (2, 3), (5, 6)),
            ((1, 2),),
        ),
        (
            "small_to_large_merge",
            64,
            tuple((vertex, vertex + 1) for vertex in range(31)) + ((32, 33),),
            ((31, 32),),
        ),
        (
            "large_component_merge",
            128,
            tuple((vertex, vertex + 1) for vertex in range(47))
            + tuple((vertex, vertex + 1) for vertex in range(64, 111)),
            ((47, 64),),
        ),
        (
            "hub_bridge",
            258,
            tuple((0, vertex) for vertex in range(1, 128))
            + tuple((128, vertex) for vertex in range(129, 256)),
            ((0, 128),),
        ),
    )
    for index, (workload_class, vertices, pairs, update_pairs) in enumerate(
        definitions, start=1
    ):
        graph = _reciprocal_graph(
            f"cc_{workload_class}_base", vertices, pairs, salt=index
        )
        update = _reciprocal_update(
            f"cc_{workload_class}_insert_u1",
            vertices,
            update_pairs,
            salt=index,
            diff=1,
        )
        analyze_reciprocal_update(graph, update)
        fixtures.append(
            ConnectedComponentsFixture(
                f"cc_{workload_class}", workload_class, "semantic", graph, update
            )
        )

    zero_net_graph = _reciprocal_graph(
        "cc_zero_net_base", 8, ((0, 1), (2, 3)), salt=41
    )
    zero_net_weight = _weight(0, 1, 41)
    zero_net_update = SliceGraph(
        "cc_zero_net_delete_then_reinsert_u2",
        8,
        (
            SliceRecord(0, 1, zero_net_weight, -1),
            SliceRecord(0, 1, zero_net_weight, 1),
            SliceRecord(1, 0, zero_net_weight, -1),
            SliceRecord(1, 0, zero_net_weight, 1),
        ),
    )
    zero_net_analysis = analyze_reciprocal_update(
        zero_net_graph, zero_net_update
    )
    if not zero_net_analysis.zero_net:
        raise AssertionError("frozen zero-net CC fixture changed the graph")
    fixtures.append(
        ConnectedComponentsFixture(
            "cc_zero_net",
            "zero_net_no_analytic_version",
            "semantic",
            zero_net_graph,
            zero_net_update,
        )
    )

    pair_vertices = 8192
    pair_count = pair_vertices // 2
    pair_base_pairs = tuple((2 * component, 2 * component + 1) for component in range(pair_count))
    pair_graph = _reciprocal_graph(
        "cc_pair_bank_base_v8192", pair_vertices, pair_base_pairs, salt=17
    )
    bridges = [(2 * component + 1, 2 * (component + 1)) for component in range(pair_count - 1)]
    bridges.append((0, pair_vertices - 1))
    for size in CC_BATCH_SIZES:
        update = _reciprocal_update(
            f"cc_pair_bank_insert_u{size}",
            pair_vertices,
            bridges[:size],
            salt=23,
            diff=1,
        )
        analyze_reciprocal_update(pair_graph, update)
        fixtures.append(
            ConnectedComponentsFixture(
                f"cc_pair_bank_insert_u{size}",
                "dense_nested_component_merge",
                "screening" if size < 4096 else "dense",
                pair_graph,
                update,
            )
        )

    deletion_vertices = 130
    deletion_pairs = tuple((vertex, vertex + 1) for vertex in range(deletion_vertices - 1))
    deletion_graph = _reciprocal_graph(
        "cc_deletion_chain_base_v130", deletion_vertices, deletion_pairs, salt=31
    )
    for size in (8, 64):
        selected = tuple(deletion_pairs[2 * index] for index in range(size))
        update = _reciprocal_update(
            f"cc_deletion_chain_delete_u{size}",
            deletion_vertices,
            selected,
            salt=31,
            diff=-1,
        )
        analyze_reciprocal_update(deletion_graph, update)
        fixtures.append(
            ConnectedComponentsFixture(
                f"cc_deletion_chain_delete_u{size}",
                "reciprocal_deletion_full_recompute",
                "fallback",
                deletion_graph,
                update,
            )
        )
    return tuple(fixtures)
