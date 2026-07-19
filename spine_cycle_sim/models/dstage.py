"""D-stage tile schedule helpers.

This module mirrors the host-side partitioned tile schedule reference used by
the HLS integration smoke. It intentionally models schedule structure first;
timing calibration is layered on top of these counters.
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import asdict, dataclass
from math import ceil
from typing import Any

from spine_cycle_sim.workloads import Edge


@dataclass(frozen=True)
class TileScheduleEntry:
    partition: int
    tile: int
    tile_begin: int
    tile_end: int
    tile_size: int
    tile_work: int
    clipped_ranges: int
    fallback_used: bool
    nonempty: bool
    path: str
    gathered_vertex_words: int
    swept_vertex_words: int
    scattered_vertex_words: int


@dataclass(frozen=True)
class TileSchedule:
    entries: tuple[TileScheduleEntry, ...]
    touched_tiles: int
    marked_tiles: int
    nonempty_tiles: int
    empty_tile_passes: int
    fallback_used: int
    row_lookups: int
    clipped_ranges: int
    active_record_replays: int
    fast_path_tiles: int
    full_path_tiles: int
    gathered_vertex_words: int
    swept_vertex_words: int
    scattered_vertex_words: int
    active_records: int
    active_sources: int
    traversed_edges: int

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["entries"] = [asdict(entry) for entry in self.entries]
        return data


def build_tile_schedule(
    edges: list[Edge],
    vertices: int,
    config: Any,
    active_sources: set[int] | None = None,
) -> TileSchedule:
    """Build the cold-partition D-stage tile schedule for one convergence pass."""

    if active_sources is None:
        active_sources = {edge.src for edge in edges}
    active_sources = set(active_sources)
    num_partitions = int(getattr(config, "num_partitions"))
    vs_partition_size = int(getattr(config, "vs_partition_size"))
    tile_vertices = int(getattr(config, "conv_tile_vertices", 65_536))
    tiny_threshold = int(getattr(config, "tiny_active_threshold", 4096))
    replay_fallback_threshold = int(
        getattr(config, "conv_tile_replay_fallback_threshold", 65_536)
    )
    touch_fallback_threshold = int(
        getattr(
            config,
            "conv_tile_touch_fallback_threshold",
            ceil(max(1, vs_partition_size) / max(1, tile_vertices)),
        )
    )

    rows: dict[tuple[int, int], list[Edge]] = defaultdict(list)
    for edge in edges:
        if edge.src not in active_sources:
            continue
        partition = max(0, min(num_partitions - 1, edge.dst // max(1, vs_partition_size)))
        rows[(partition, edge.src)].append(edge)
    for row_edges in rows.values():
        row_edges.sort(key=lambda edge: edge.dst)

    entries: list[TileScheduleEntry] = []
    touched_tiles = 0
    marked_tiles = 0
    nonempty_tiles = 0
    empty_tile_passes = 0
    fallback_used = 0
    row_lookups = 0
    clipped_ranges = 0
    active_record_replays = 0
    fast_path_tiles = 0
    full_path_tiles = 0
    gathered_vertex_words = 0
    swept_vertex_words = 0
    scattered_vertex_words = 0
    active_records = 0

    for partition in range(num_partitions):
        partition_begin = partition * vs_partition_size
        if partition_begin >= vertices:
            continue
        partition_end = min(vertices, partition_begin + vs_partition_size)
        partition_size = partition_end - partition_begin
        valid_tiles = ceil(partition_size / max(1, tile_vertices))
        if valid_tiles <= 0:
            continue

        partition_sources = sorted(
            src for src in active_sources if (partition, src) in rows
        )
        active_records += len(partition_sources)
        if not partition_sources:
            continue

        discovered: set[int] = set()
        for src in partition_sources:
            row_lookups += 1
            row_edges = rows.get((partition, src), [])
            if not row_edges:
                continue
            first_tile = (row_edges[0].dst - partition_begin) // tile_vertices
            last_tile = (row_edges[-1].dst - partition_begin) // tile_vertices
            first_tile = max(0, min(valid_tiles - 1, first_tile))
            last_tile = max(0, min(valid_tiles - 1, last_tile))
            for tile in range(first_tile, last_tile + 1):
                if tile not in discovered:
                    marked_tiles += 1
                discovered.add(tile)
        if not discovered:
            continue

        force_fallback = (
            len(discovered) > touch_fallback_threshold
            or len(partition_sources) * len(discovered) > replay_fallback_threshold
        )
        touched = set(range(valid_tiles)) if force_fallback else discovered
        if force_fallback:
            fallback_used += 1
        touched_tiles += len(touched)

        for tile in sorted(touched):
            tile_begin = partition_begin + tile * tile_vertices
            tile_end = min(partition_end, tile_begin + tile_vertices)
            tile_size = max(0, tile_end - tile_begin)
            if tile_size <= 0:
                continue
            tile_work = 0
            tile_clipped_ranges = 0
            for src in partition_sources:
                active_record_replays += 1
                row_lookups += 1
                row_edges = rows.get((partition, src), [])
                count = sum(1 for edge in row_edges if tile_begin <= edge.dst < tile_end)
                if count:
                    tile_clipped_ranges += 1
                    tile_work += count
            tile_nonempty = tile_work > 0
            clipped_ranges += tile_clipped_ranges
            if tile_nonempty:
                nonempty_tiles += 1
            else:
                empty_tile_passes += 1

            fast_path = (not force_fallback) and tile_work <= tiny_threshold
            if fast_path:
                fast_path_tiles += 1
                tile_gathered = tile_work
                tile_swept = 0
                tile_scattered = tile_work
                gathered_vertex_words += tile_gathered
                scattered_vertex_words += tile_scattered
                path = "fast"
            else:
                full_path_tiles += 1
                tile_gathered = 0
                tile_swept = tile_size * 2
                tile_scattered = 0
                swept_vertex_words += tile_swept
                path = "full"
            entries.append(
                TileScheduleEntry(
                    partition=partition,
                    tile=tile,
                    tile_begin=tile_begin,
                    tile_end=tile_end,
                    tile_size=tile_size,
                    tile_work=tile_work,
                    clipped_ranges=tile_clipped_ranges,
                    fallback_used=force_fallback,
                    nonempty=tile_nonempty,
                    path=path,
                    gathered_vertex_words=tile_gathered,
                    swept_vertex_words=tile_swept,
                    scattered_vertex_words=tile_scattered,
                )
            )

    return TileSchedule(
        entries=tuple(entries),
        touched_tiles=touched_tiles,
        marked_tiles=marked_tiles,
        nonempty_tiles=nonempty_tiles,
        empty_tile_passes=empty_tile_passes,
        fallback_used=fallback_used,
        row_lookups=row_lookups,
        clipped_ranges=clipped_ranges,
        active_record_replays=active_record_replays,
        fast_path_tiles=fast_path_tiles,
        full_path_tiles=full_path_tiles,
        gathered_vertex_words=gathered_vertex_words,
        swept_vertex_words=swept_vertex_words,
        scattered_vertex_words=scattered_vertex_words,
        active_records=active_records,
        active_sources=len(active_sources),
        traversed_edges=sum(entry.tile_work for entry in entries),
    )
