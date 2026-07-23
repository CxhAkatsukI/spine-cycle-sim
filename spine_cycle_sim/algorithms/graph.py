"""Dynamic directed graph semantics shared by functional oracles."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from pathlib import Path

from spine_cycle_sim.workloads import Edge


class UpdateOperation(str, Enum):
    UPSERT = "upsert"
    DELETE = "delete"


@dataclass(frozen=True)
class EdgeUpdate:
    src: int
    dst: int
    weight: int = 1
    operation: UpdateOperation = UpdateOperation.UPSERT


@dataclass(frozen=True)
class BatchEffect:
    inserted: int
    deleted: int
    decreased: int
    increased: int
    unchanged: int
    missing_deletes: int
    changed_sources: frozenset[int]
    changed_destinations: frozenset[int]

    @property
    def changed_edges(self) -> int:
        return self.inserted + self.deleted + self.decreased + self.increased


class DynamicGraph:
    """Directed simple graph with last-write-wins batch updates."""

    def __init__(self, vertices: int) -> None:
        if vertices <= 0:
            raise ValueError("vertices must be positive")
        self.vertices = vertices
        self._adjacency: list[dict[int, int]] = [dict() for _ in range(vertices)]
        self._edge_count = 0

    @classmethod
    def from_edges(cls, vertices: int, edges: list[Edge]) -> DynamicGraph:
        graph = cls(vertices)
        graph.apply_batch(
            [EdgeUpdate(edge.src, edge.dst, edge.weight) for edge in edges]
        )
        return graph

    @property
    def edge_count(self) -> int:
        return self._edge_count

    def out_degree(self, src: int) -> int:
        self._validate_vertex(src)
        return len(self._adjacency[src])

    def out_edges(self, src: int):
        self._validate_vertex(src)
        return self._adjacency[src].items()

    def weight(self, src: int, dst: int) -> int | None:
        self._validate_pair(src, dst)
        return self._adjacency[src].get(dst)

    def edges(self) -> list[Edge]:
        return [
            Edge(src, dst, weight)
            for src, row in enumerate(self._adjacency)
            for dst, weight in sorted(row.items())
        ]

    def apply_batch(self, updates: list[EdgeUpdate]) -> BatchEffect:
        coalesced: dict[tuple[int, int], EdgeUpdate] = {}
        for update in updates:
            self._validate_pair(update.src, update.dst)
            if update.weight < 0:
                raise ValueError("edge weights must be non-negative integers")
            coalesced[(update.src, update.dst)] = update

        inserted = deleted = decreased = increased = unchanged = missing = 0
        changed_sources: set[int] = set()
        changed_destinations: set[int] = set()
        for (src, dst), update in coalesced.items():
            row = self._adjacency[src]
            old_weight = row.get(dst)
            if update.operation == UpdateOperation.DELETE:
                if old_weight is None:
                    missing += 1
                    continue
                del row[dst]
                self._edge_count -= 1
                deleted += 1
            elif old_weight is None:
                row[dst] = update.weight
                self._edge_count += 1
                inserted += 1
            elif update.weight < old_weight:
                row[dst] = update.weight
                decreased += 1
            elif update.weight > old_weight:
                row[dst] = update.weight
                increased += 1
            else:
                unchanged += 1
                continue
            changed_sources.add(src)
            changed_destinations.add(dst)
        return BatchEffect(
            inserted=inserted,
            deleted=deleted,
            decreased=decreased,
            increased=increased,
            unchanged=unchanged,
            missing_deletes=missing,
            changed_sources=frozenset(changed_sources),
            changed_destinations=frozenset(changed_destinations),
        )

    def _validate_vertex(self, vertex: int) -> None:
        if vertex < 0 or vertex >= self.vertices:
            raise ValueError(f"vertex {vertex} is outside [0, {self.vertices})")

    def _validate_pair(self, src: int, dst: int) -> None:
        self._validate_vertex(src)
        self._validate_vertex(dst)


@dataclass(frozen=True)
class LoadedEdgeList:
    graph: DynamicGraph
    metadata: dict[str, str]
    updates: tuple[EdgeUpdate, ...]


def load_spine_edge_list(path: str | Path) -> LoadedEdgeList:
    """Load the exact Spine slice format: comments plus src dst weight diff."""

    source = Path(path)
    metadata: dict[str, str] = {}
    raw: list[tuple[int, int, int, int]] = []
    max_vertex = -1
    for line_number, raw_line in enumerate(source.read_text(encoding="utf-8").splitlines(), 1):
        line = raw_line.strip()
        if not line:
            continue
        if line.startswith("#"):
            item = line[1:].strip()
            if "=" in item:
                key, value = item.split("=", 1)
                metadata[key.strip()] = value.strip()
            continue
        fields = line.split()
        if len(fields) < 2 or len(fields) > 4:
            raise ValueError(f"{source}:{line_number}: expected src dst [weight [diff]]")
        src, dst = int(fields[0], 0), int(fields[1], 0)
        weight = int(fields[2], 0) if len(fields) >= 3 else 1
        diff = int(fields[3], 0) if len(fields) >= 4 else 1
        if src < 0 or dst < 0 or weight < 0 or diff == 0:
            raise ValueError(f"{source}:{line_number}: invalid edge record")
        raw.append((src, dst, weight, diff))
        max_vertex = max(max_vertex, src, dst)
    if not raw:
        raise ValueError(f"edge-list file is empty: {source}")
    vertices = int(metadata.get("vertices", max_vertex + 1), 0)
    if vertices <= max_vertex:
        raise ValueError(f"vertices={vertices} does not cover max vertex {max_vertex}")

    # A slice may contain repeated differential records. Preserve its established
    # coalescing rule before converting to the simple-graph update contract.
    grouped: dict[tuple[int, int], tuple[int, int]] = {}
    for src, dst, weight, diff in raw:
        old_weight, diff_sum = grouped.get((src, dst), (weight, 0))
        grouped[(src, dst)] = (min(old_weight, weight), diff_sum + diff)
    updates = tuple(
        EdgeUpdate(
            src,
            dst,
            weight,
            UpdateOperation.UPSERT if diff_sum > 0 else UpdateOperation.DELETE,
        )
        for (src, dst), (weight, diff_sum) in sorted(grouped.items())
        if diff_sum != 0
    )
    graph = DynamicGraph(vertices)
    graph.apply_batch(list(updates))
    return LoadedEdgeList(graph=graph, metadata=metadata, updates=updates)
