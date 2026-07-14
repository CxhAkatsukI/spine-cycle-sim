"""Synthetic graph workloads for Spine simulator validation."""

from __future__ import annotations

from dataclasses import dataclass, field
import random


@dataclass(frozen=True)
class Edge:
    src: int
    dst: int
    weight: int = 1


@dataclass
class Workload:
    name: str
    vertices: int
    edges: list[Edge]
    source: int = 0
    metadata: dict[str, int | str] = field(default_factory=dict)

    @property
    def edge_count(self) -> int:
        return len(self.edges)


def list_workloads() -> list[str]:
    return ["balanced_partition", "chain", "hotdst", "random_rmat", "spread", "star"]


def generate_workload(
    name: str,
    vertices: int,
    edges: int | None,
    source: int,
    num_partitions: int,
    seed: int = 1,
) -> Workload:
    if vertices <= 0:
        raise ValueError("vertices must be positive")
    if edges is None:
        edges = max(0, vertices - 1)
    if edges < 0:
        raise ValueError("edges must be non-negative")

    name = name.lower()
    if name == "chain":
        return _chain(vertices, edges, source)
    if name == "star":
        return _star(vertices, edges, source, num_partitions)
    if name == "spread":
        return _spread(vertices, edges, source, num_partitions)
    if name == "hotdst":
        return _hotdst(vertices, edges, source)
    if name == "balanced_partition":
        return _balanced_partition(vertices, edges, source, num_partitions)
    if name == "random_rmat":
        return _random_rmat(vertices, edges, source, seed)
    raise ValueError(f"unknown workload {name!r}; choices: {', '.join(list_workloads())}")


def _chain(vertices: int, edges: int, source: int) -> Workload:
    data: list[Edge] = []
    span = max(1, vertices - 1)
    for i in range(edges):
        src = i % span
        dst = (src + 1) % vertices
        data.append(Edge(src, dst, 1))
    return Workload("chain", vertices, data, source, {"shape": "high_diameter"})


def _star(vertices: int, edges: int, source: int, num_partitions: int) -> Workload:
    data: list[Edge] = []
    # Destination IDs are chosen from one destination partition. This matches the
    # current Spine stress cases where low-diameter fanout can bottleneck one L1
    # partition during carry.
    for i in range(edges):
        dst = ((i + 1) * num_partitions) % vertices
        if dst == source:
            dst = (dst + num_partitions) % vertices
        data.append(Edge(source, dst, 1))
    return Workload("star", vertices, data, source, {"shape": "low_diameter_one_partition"})


def _spread(vertices: int, edges: int, source: int, num_partitions: int) -> Workload:
    del source
    data: list[Edge] = []
    active_sources = max(1, min(vertices, max(1, edges // 16)))
    for i in range(edges):
        src = i % active_sources
        dst = ((i // active_sources) * num_partitions) % vertices
        if dst == src:
            dst = (dst + num_partitions) % vertices
        data.append(Edge(src, dst, 1))
    return Workload("spread", vertices, data, 0, {"shape": "multi_source_one_partition"})


def _hotdst(vertices: int, edges: int, source: int) -> Workload:
    data = [Edge((i + 1) % vertices, source, 1) for i in range(edges)]
    return Workload("hotdst", vertices, data, source, {"shape": "single_hot_destination"})


def _balanced_partition(vertices: int, edges: int, source: int, num_partitions: int) -> Workload:
    data: list[Edge] = []
    stride = max(1, vertices // max(1, num_partitions))
    for i in range(edges):
        partition = i % num_partitions
        dst = (partition + (i // num_partitions) * stride) % vertices
        src = (dst + 1) % vertices
        if src == dst:
            src = source
        data.append(Edge(src, dst, 1))
    return Workload("balanced_partition", vertices, data, source, {"shape": "balanced_destination_partitions"})


def _random_rmat(vertices: int, edges: int, source: int, seed: int) -> Workload:
    rng = random.Random(seed)
    data: list[Edge] = []
    scale = max(1, (vertices - 1).bit_length())
    for _ in range(edges):
        src = 0
        dst = 0
        step = 1 << (scale - 1)
        while step > 0:
            r = rng.random()
            if r < 0.57:
                pass
            elif r < 0.76:
                dst += step
            elif r < 0.95:
                src += step
            else:
                src += step
                dst += step
            step >>= 1
        data.append(Edge(src % vertices, dst % vertices, 1))
    return Workload("random_rmat", vertices, data, source, {"shape": "skewed_rmat", "seed": seed})
