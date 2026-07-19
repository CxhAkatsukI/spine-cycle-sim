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
    vs_partition_size: int = 1,
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
        return _star(vertices, edges, source, num_partitions, vs_partition_size)
    if name == "spread":
        return _spread(vertices, edges, source, num_partitions, vs_partition_size)
    if name == "hotdst":
        return _hotdst(vertices, edges, source)
    if name == "balanced_partition":
        return _balanced_partition(vertices, edges, source, num_partitions, vs_partition_size)
    if name == "random_rmat":
        return _random_rmat(vertices, edges, source, seed)
    raise ValueError(f"unknown workload {name!r}; choices: {', '.join(list_workloads())}")


def generate_tile_workload(
    tile_work: list[int],
    *,
    vertices: int | None = None,
    source: int = 0,
    tile_vertices: int = 65_536,
    max_vertices: int = 16_777_216,
) -> Workload:
    """Generate the same one-source tile-work shape as the HLS host smoke."""

    if not tile_work:
        raise ValueError("tile_work must contain at least one count")
    if any(count < 0 for count in tile_work):
        raise ValueError("tile_work counts must be non-negative")
    if sum(tile_work) <= 0:
        raise ValueError("tile_work must contain at least one edge")
    data: list[Edge] = []
    for tile, count in enumerate(tile_work):
        if count + 1 > tile_vertices:
            raise ValueError("tile_work count exceeds supported tile payload")
        tile_base = tile * tile_vertices
        for i in range(count):
            dst = tile_base + 1 + i
            if dst >= max_vertices:
                raise ValueError("tile_work destination exceeds max_vertices")
            weight = 1 + ((tile * 17 + i) & 31)
            data.append(Edge(source, dst, weight))
    inferred_vertices = max(edge.dst for edge in data) + 1
    total_vertices = vertices if vertices is not None else inferred_vertices
    if total_vertices < inferred_vertices:
        raise ValueError("vertices is smaller than generated tile_work dst range")
    return Workload(
        "tile_work",
        total_vertices,
        data,
        source,
        {"shape": "tile_work", "tile_work": ",".join(str(v) for v in tile_work)},
    )


def generate_partition_tile_workload(
    partition_tile_work: dict[int, list[int]],
    *,
    vertices: int | None = None,
    source: int = 0,
    tile_vertices: int = 65_536,
    vs_partition_size: int = 1_048_576,
    max_vertices: int = 16_777_216,
) -> Workload:
    """Generate the same multi-partition tile-work shape as the HLS host smoke."""

    if not partition_tile_work:
        raise ValueError("partition_tile_work must contain at least one partition")
    data: list[Edge] = []
    metadata_parts: list[str] = []
    for partition in sorted(partition_tile_work):
        if partition < 0:
            raise ValueError("partition_tile_work partition must be non-negative")
        tile_work = partition_tile_work[partition]
        if not tile_work:
            raise ValueError("partition_tile_work tile list must be non-empty")
        if any(count < 0 for count in tile_work):
            raise ValueError("partition_tile_work counts must be non-negative")
        metadata_parts.append(
            f"{partition}:" + ",".join(str(value) for value in tile_work)
        )
        partition_base = partition * vs_partition_size
        for tile, count in enumerate(tile_work):
            if count + 1 > tile_vertices:
                raise ValueError(
                    "partition_tile_work count exceeds supported tile payload"
                )
            tile_base = tile * tile_vertices
            for i in range(count):
                local_dst = tile_base + 1 + i
                if local_dst >= vs_partition_size:
                    raise ValueError(
                        "partition_tile_work destination exceeds partition range"
                    )
                dst = partition_base + local_dst
                if dst >= max_vertices:
                    raise ValueError(
                        "partition_tile_work destination exceeds max_vertices"
                    )
                weight = 1 + ((partition * 31 + tile * 17 + i) & 31)
                data.append(Edge(source, dst, weight))
    if not data:
        raise ValueError("partition_tile_work must contain at least one edge")
    inferred_vertices = max(edge.dst for edge in data) + 1
    total_vertices = vertices if vertices is not None else inferred_vertices
    if total_vertices < inferred_vertices:
        raise ValueError(
            "vertices is smaller than generated partition_tile_work dst range"
        )
    return Workload(
        "partition_tile_work",
        total_vertices,
        data,
        source,
        {
            "shape": "partition_tile_work",
            "partition_tile_work": ";".join(metadata_parts),
        },
    )


def _chain(vertices: int, edges: int, source: int) -> Workload:
    data: list[Edge] = []
    span = max(1, vertices - 1)
    for i in range(edges):
        src = i % span
        dst = (src + 1) % vertices
        data.append(Edge(src, dst, 1))
    return Workload("chain", vertices, data, source, {"shape": "high_diameter"})


def _star(
    vertices: int,
    edges: int,
    source: int,
    num_partitions: int,
    vs_partition_size: int,
) -> Workload:
    data: list[Edge] = []
    del num_partitions
    # Destination IDs are chosen from one current Spine destination partition
    # range: dst / VS_PARTITION_SIZE == 0.
    local_span = max(1, min(vertices, max(1, vs_partition_size)))
    for i in range(edges):
        dst = (i + 1) % local_span
        if dst == source:
            dst = (dst + 1) % local_span
        data.append(Edge(source, dst, 1))
    return Workload("star", vertices, data, source, {"shape": "low_diameter_one_partition"})


def _spread(
    vertices: int,
    edges: int,
    source: int,
    num_partitions: int,
    vs_partition_size: int,
) -> Workload:
    del source
    del num_partitions
    data: list[Edge] = []
    active_sources = max(1, min(vertices, max(1, edges // 16)))
    local_span = max(1, min(vertices, max(1, vs_partition_size)))
    for i in range(edges):
        src = i % active_sources
        dst = (i // active_sources) % local_span
        if dst == src:
            dst = (dst + 1) % local_span
        data.append(Edge(src, dst, 1))
    return Workload("spread", vertices, data, 0, {"shape": "multi_source_one_partition"})


def _hotdst(vertices: int, edges: int, source: int) -> Workload:
    data = [Edge((i + 1) % vertices, source, 1) for i in range(edges)]
    return Workload("hotdst", vertices, data, source, {"shape": "single_hot_destination"})


def _balanced_partition(
    vertices: int,
    edges: int,
    source: int,
    num_partitions: int,
    vs_partition_size: int,
) -> Workload:
    data: list[Edge] = []
    local_span = max(1, min(max(1, vs_partition_size), max(1, vertices)))
    for i in range(edges):
        partition = i % num_partitions
        dst = partition * vs_partition_size + ((i // num_partitions) % local_span)
        if dst >= vertices:
            dst %= vertices
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
