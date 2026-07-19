#!/usr/bin/env python3
"""Extract real graph slices and translate them into host-runnable D-stage cases."""

from __future__ import annotations

import argparse
import csv
import json
import math
import sys
from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.compare_dstage_tile_schedule import workload_from_case  # noqa: E402
from spine_cycle_sim.models import SpineConfig, load_config  # noqa: E402
from spine_cycle_sim.models.dstage import TileSchedule, build_tile_schedule  # noqa: E402
from spine_cycle_sim.workloads import Edge, Workload  # noqa: E402

DEFAULT_GRAPH = Path("/home/chuxiao/ReGraph/dataset/amazon-2008.mtx")
DEFAULT_CONFIG = ROOT / "configs/spine_current.yaml"

METRIC_FIELDS = [
    "case",
    "sweep",
    "translation",
    "selector",
    "selector_start",
    "raw_active_sources",
    "raw_edges",
    "raw_partition_count",
    "raw_touched_tiles",
    "raw_fast_path_tiles",
    "raw_full_path_tiles",
    "raw_fallback_used",
    "raw_clipped_ranges",
    "raw_replay_proxy",
    "raw_avg_edges_per_source",
    "raw_max_edges_per_source",
    "raw_max_tile_work",
    "translated_edges",
    "translated_partition_count",
    "translated_touched_tiles",
    "translated_fast_path_tiles",
    "translated_full_path_tiles",
    "translated_fallback_used",
    "translated_clipped_ranges",
    "translated_replay_proxy",
    "translated_max_tile_work",
    "edge_scale",
    "replay_scale",
    "coverage_status",
    "coverage_notes",
    "args",
    "purpose",
]


@dataclass(frozen=True)
class GraphStats:
    edge_count: int
    min_raw_vertex: int
    max_raw_vertex: int
    vertex_count: int
    id_offset: int
    source_degrees: dict[int, int]


@dataclass(frozen=True)
class SourceSelection:
    selector: str
    sources: tuple[int, ...]
    start: int | None = None


@dataclass(frozen=True)
class TranslatedCase:
    case: str
    sweep: str
    args: tuple[str, ...]
    purpose: str
    translation: str
    selector: str
    selector_start: int | None
    raw_schedule: TileSchedule
    translated_schedule: TileSchedule
    raw_edges: int
    translated_edges: int
    raw_max_edges_per_source: int


@dataclass(frozen=True)
class ExactSliceCase:
    case: str
    sweep: str
    args: tuple[str, ...]
    purpose: str
    selector: str
    selector_start: int | None
    slice_path: Path
    schedule: TileSchedule
    raw_edges: int
    raw_max_edges_per_source: int


def parse_edge_line(line: str) -> tuple[int, int] | None:
    stripped = line.strip()
    if not stripped or stripped.startswith("%") or stripped.startswith("#"):
        return None
    parts = stripped.split()
    if len(parts) < 2:
        return None
    try:
        values = [int(parts[index]) for index in range(min(3, len(parts)))]
    except ValueError:
        return None
    if len(values) >= 3 and values[2] >= 0 and values[0] > 0 and values[1] > 0:
        # MatrixMarket size lines are usually "rows cols nnz"; amazon-2008 in this
        # workspace is a bare edge list, so this only skips true 3-field headers.
        if len(parts) == 3 and values[2] > values[0] and values[2] > values[1]:
            return None
    return values[0], values[1]


def iter_raw_edges(path: Path) -> Iterable[tuple[int, int]]:
    with path.open(errors="ignore") as f:
        for line in f:
            edge = parse_edge_line(line)
            if edge is not None:
                yield edge


def scan_graph(path: Path) -> GraphStats:
    raw_source_degrees: dict[int, int] = defaultdict(int)
    min_vertex: int | None = None
    max_vertex = -1
    edge_count = 0
    for src, dst in iter_raw_edges(path):
        edge_count += 1
        raw_source_degrees[src] += 1
        if min_vertex is None:
            min_vertex = min(src, dst)
        else:
            min_vertex = min(min_vertex, src, dst)
        max_vertex = max(max_vertex, src, dst)
    if edge_count == 0 or min_vertex is None:
        raise ValueError(f"no edges found in {path}")
    id_offset = 0 if min_vertex == 0 else 1
    source_degrees = {
        src - id_offset: degree
        for src, degree in raw_source_degrees.items()
        if src >= id_offset
    }
    vertex_count = max_vertex - id_offset + 1
    return GraphStats(
        edge_count=edge_count,
        min_raw_vertex=min_vertex,
        max_raw_vertex=max_vertex,
        vertex_count=vertex_count,
        id_offset=id_offset,
        source_degrees=source_degrees,
    )


def iter_edges(path: Path, id_offset: int) -> Iterable[Edge]:
    for src, dst in iter_raw_edges(path):
        yield Edge(src - id_offset, dst - id_offset, 1)


def top_sources(source_degrees: dict[int, int], count: int) -> tuple[int, ...]:
    ordered = sorted(source_degrees, key=lambda src: (-source_degrees[src], src))
    return tuple(ordered[:count])


def densest_window(
    source_degrees: dict[int, int],
    vertex_count: int,
    window_size: int,
) -> tuple[int, tuple[int, ...]]:
    if window_size >= vertex_count:
        sources = tuple(src for src in range(vertex_count) if source_degrees.get(src, 0) > 0)
        return 0, sources
    dense = [0] * vertex_count
    for src, degree in source_degrees.items():
        if 0 <= src < vertex_count:
            dense[src] = degree
    current = sum(dense[:window_size])
    best_sum = current
    best_start = 0
    for start in range(1, vertex_count - window_size + 1):
        current += dense[start + window_size - 1] - dense[start - 1]
        if current > best_sum:
            best_sum = current
            best_start = start
    sources = tuple(
        src
        for src in range(best_start, best_start + window_size)
        if source_degrees.get(src, 0) > 0
    )
    return best_start, sources


def stride_sources(source_degrees: dict[int, int], count: int) -> tuple[int, ...]:
    ordered = sorted(source_degrees)
    if len(ordered) <= count:
        return tuple(ordered)
    out: list[int] = []
    for index in range(count):
        source = ordered[math.floor(index * len(ordered) / count)]
        if not out or out[-1] != source:
            out.append(source)
    return tuple(out[:count])


def select_sources(stats: GraphStats) -> list[SourceSelection]:
    selections: list[SourceSelection] = []
    for count in (1, 8, 64, 512, 4096, 8192):
        sources = top_sources(stats.source_degrees, count)
        if sources:
            selections.append(SourceSelection(f"top{len(sources)}", sources))
    for window_size in (64, 512, 4096, 8192):
        start, sources = densest_window(
            stats.source_degrees,
            stats.vertex_count,
            window_size,
        )
        if sources:
            selections.append(
                SourceSelection(f"densewin{window_size}_active{len(sources)}", sources, start)
            )
    for count in (512, 4096):
        sources = stride_sources(stats.source_degrees, count)
        if sources:
            selections.append(SourceSelection(f"stride{len(sources)}", sources))
    return selections


def schedule_for_edges(
    edges: list[Edge],
    active_sources: set[int],
    vertices: int,
    config: SpineConfig,
) -> TileSchedule:
    return build_tile_schedule(edges, vertices, config, active_sources=active_sources)


def collect_slice_edges(
    graph: Path,
    stats: GraphStats,
    selections: list[SourceSelection],
) -> dict[str, list[Edge]]:
    source_to_selectors: dict[int, list[str]] = defaultdict(list)
    for selection in selections:
        for source in selection.sources:
            source_to_selectors[source].append(selection.selector)
    slice_edges = {selection.selector: [] for selection in selections}
    for edge in iter_edges(graph, stats.id_offset):
        for selector in source_to_selectors.get(edge.src, []):
            slice_edges[selector].append(edge)
    return slice_edges


def source_edge_counts(edges: list[Edge]) -> dict[int, int]:
    counts: dict[int, int] = defaultdict(int)
    for edge in edges:
        counts[edge.src] += 1
    return counts


def coalesced_edges(edges: list[Edge]) -> list[Edge]:
    grouped: dict[tuple[int, int], int] = {}
    for edge in edges:
        key = (edge.src, edge.dst)
        grouped[key] = min(edge.weight, grouped.get(key, edge.weight))
    return [
        Edge(src, dst, weight)
        for (src, dst), weight in sorted(grouped.items())
    ]


def partition_tile_totals(edges: list[Edge], config: SpineConfig) -> dict[int, dict[int, int]]:
    totals: dict[int, dict[int, int]] = defaultdict(lambda: defaultdict(int))
    for edge in edges:
        partition = max(0, min(config.num_partitions - 1, edge.dst // config.vs_partition_size))
        local = edge.dst - partition * config.vs_partition_size
        tile = max(0, local // config.conv_tile_vertices)
        totals[partition][tile] += 1
    return totals


def to_partition_specs(totals: dict[int, dict[int, int]]) -> list[str]:
    specs: list[str] = []
    for partition in sorted(totals):
        tile_counts = totals[partition]
        max_tile = max(tile_counts)
        counts = [tile_counts.get(tile, 0) for tile in range(max_tile + 1)]
        specs.append(f"{partition}:" + ",".join(str(count) for count in counts))
    return specs


def average_partition_specs(
    totals: dict[int, dict[int, int]],
    source_count: int,
) -> tuple[list[str], int]:
    averaged: dict[int, dict[int, int]] = defaultdict(dict)
    translated_edges_per_source = 0
    for partition, tile_counts in totals.items():
        max_tile = max(tile_counts)
        for tile in range(max_tile + 1):
            count = tile_counts.get(tile, 0)
            if count <= 0:
                averaged[partition][tile] = 0
                continue
            per_source = max(1, int(round(count / source_count)))
            averaged[partition][tile] = per_source
        translated_edges_per_source += sum(averaged[partition].values())
    return to_partition_specs(averaged), source_count * translated_edges_per_source


def workload_for_args(args: tuple[str, ...], config: SpineConfig) -> Workload:
    case = {"case": "translated", "args": list(args)}
    return workload_from_case(case, config)


def single_partition_tile_count(schedule: TileSchedule) -> tuple[int, int] | None:
    partitions = {entry.partition for entry in schedule.entries}
    if len(partitions) != 1:
        return None
    partition = next(iter(partitions))
    max_tile = max((entry.tile for entry in schedule.entries), default=-1)
    if max_tile < 0:
        return None
    return partition, max_tile + 1


def coverage_for(
    schedule: TileSchedule,
    translated_edges: int,
    config: SpineConfig,
) -> tuple[str, str]:
    notes: list[str] = []
    status = "trusted_shape"
    partition_count = len({entry.partition for entry in schedule.entries})
    replay_proxy = schedule.active_records * schedule.touched_tiles
    if translated_edges > config.batch_size_edges:
        notes.append("exceeds_current_l0_batch_capacity")
        status = "untrusted_shape"
    if partition_count <= 1:
        notes.append("single_partition_real_id_scope")
    if replay_proxy > 65_536:
        notes.append("replay_fallback_region")
        if status == "trusted_shape":
            status = "borderline_shape"
    if schedule.full_path_tiles > 0:
        notes.append("full_tile_path_present")
    if schedule.touched_tiles > 12:
        notes.append("more_tiles_than_amazon_raw_id_scope")
    if not notes:
        notes.append("within_phase3c_synthetic_shape")
    return status, ";".join(notes)


def write_edge_list_slice(
    path: Path,
    *,
    case_id: str,
    graph: Path,
    stats: GraphStats,
    selection: SourceSelection,
    edges: list[Edge],
) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    sorted_edges = sorted(edges, key=lambda edge: (edge.src, edge.dst, edge.weight))
    lines = [
        "# spine_real_slice_version=1",
        f"# case={case_id}",
        f"# graph={graph}",
        f"# selector={selection.selector}",
        f"# selector_start={'' if selection.start is None else selection.start}",
        f"# vertices={stats.vertex_count}",
        f"# id_offset={stats.id_offset}",
        f"# raw_edges={len(edges)}",
        f"# active_sources={len({edge.src for edge in edges})}",
        "# columns=src dst weight diff",
    ]
    lines.extend(
        f"{edge.src} {edge.dst} {edge.weight} 1"
        for edge in sorted_edges
    )
    path.write_text("\n".join(lines) + "\n")


def exact_slice_case_rows(
    graph: Path,
    stats: GraphStats,
    config: SpineConfig,
    selections: list[SourceSelection],
    out_dir: Path,
) -> tuple[list[ExactSliceCase], list[dict[str, Any]]]:
    slice_edges = collect_slice_edges(graph, stats, selections)
    by_selector = {selection.selector: selection for selection in selections}
    cases: list[ExactSliceCase] = []
    rows: list[dict[str, Any]] = []
    slice_dir = out_dir / "exact_slices"

    for selector, raw_edges in slice_edges.items():
        if not raw_edges or len(raw_edges) > config.batch_size_edges:
            continue
        selection = by_selector[selector]
        edges = coalesced_edges(raw_edges)
        active_sources = {edge.src for edge in edges}
        if not active_sources:
            continue
        schedule = schedule_for_edges(edges, active_sources, stats.vertex_count, config)
        counts = source_edge_counts(edges)
        max_edges_per_source = max(counts.values())
        case_id = f"amazon_{selector}_exact"
        slice_path = slice_dir / f"{case_id}.slice"
        write_edge_list_slice(
            slice_path,
            case_id=case_id,
            graph=graph,
            stats=stats,
            selection=selection,
            edges=edges,
        )
        args = (
            "--edge-list-slice",
            str(slice_path.resolve()),
            "--print-tile-schedule",
        )
        cases.append(
            ExactSliceCase(
                case=case_id,
                sweep="real_slice_exact",
                args=args,
                purpose=(
                    "Amazon-2008 exact source slice replay; host and simulator read "
                    "the same zero-based src/dst edge-list slice."
                ),
                selector=selector,
                selector_start=selection.start,
                slice_path=slice_path,
                schedule=schedule,
                raw_edges=len(edges),
                raw_max_edges_per_source=max_edges_per_source,
            )
        )

    for case in cases:
        coverage_status, coverage_notes = coverage_for(
            case.schedule,
            case.raw_edges,
            config,
        )
        replay = case.schedule.active_records * case.schedule.touched_tiles
        row = {
            "case": case.case,
            "sweep": case.sweep,
            "translation": "exact_edge_list",
            "selector": case.selector,
            "selector_start": "" if case.selector_start is None else case.selector_start,
            "raw_active_sources": case.schedule.active_sources,
            "raw_edges": case.raw_edges,
            "raw_partition_count": len({entry.partition for entry in case.schedule.entries}),
            "raw_touched_tiles": case.schedule.touched_tiles,
            "raw_fast_path_tiles": case.schedule.fast_path_tiles,
            "raw_full_path_tiles": case.schedule.full_path_tiles,
            "raw_fallback_used": case.schedule.fallback_used,
            "raw_clipped_ranges": case.schedule.clipped_ranges,
            "raw_replay_proxy": replay,
            "raw_avg_edges_per_source": case.raw_edges / max(1, case.schedule.active_sources),
            "raw_max_edges_per_source": case.raw_max_edges_per_source,
            "raw_max_tile_work": max(
                (entry.tile_work for entry in case.schedule.entries),
                default=0,
            ),
            "translated_edges": case.raw_edges,
            "translated_partition_count": len({entry.partition for entry in case.schedule.entries}),
            "translated_touched_tiles": case.schedule.touched_tiles,
            "translated_fast_path_tiles": case.schedule.fast_path_tiles,
            "translated_full_path_tiles": case.schedule.full_path_tiles,
            "translated_fallback_used": case.schedule.fallback_used,
            "translated_clipped_ranges": case.schedule.clipped_ranges,
            "translated_replay_proxy": replay,
            "translated_max_tile_work": max(
                (entry.tile_work for entry in case.schedule.entries),
                default=0,
            ),
            "edge_scale": 1.0,
            "replay_scale": 1.0,
            "coverage_status": coverage_status,
            "coverage_notes": coverage_notes,
            "args": " ".join(case.args),
            "purpose": case.purpose,
            "slice_path": str(case.slice_path),
        }
        rows.append(row)
    return cases, rows


def translated_case_rows(
    graph: Path,
    stats: GraphStats,
    config: SpineConfig,
    selections: list[SourceSelection],
) -> tuple[list[TranslatedCase], list[dict[str, Any]], dict[str, Any]]:
    slice_edges = collect_slice_edges(graph, stats, selections)
    cases: list[TranslatedCase] = []
    rows: list[dict[str, Any]] = []
    by_selector = {selection.selector: selection for selection in selections}

    for selector, edges in slice_edges.items():
        if not edges:
            continue
        selection = by_selector[selector]
        active_sources = {edge.src for edge in edges}
        if not active_sources:
            continue
        raw_schedule = schedule_for_edges(edges, active_sources, stats.vertex_count, config)
        totals = partition_tile_totals(edges, config)
        source_count = len(active_sources)
        edges_per_source = source_edge_counts(edges)
        max_edges_per_source = max(edges_per_source.values())

        avg_specs, translated_edges = average_partition_specs(totals, source_count)
        avg_args = (
            "--multi-source-tile-work",
            str(source_count),
            *avg_specs,
            "--print-tile-schedule",
        )
        if translated_edges <= config.batch_size_edges:
            translated = workload_for_args(avg_args, config)
            translated_schedule = schedule_for_edges(
                translated.edges,
                {edge.src for edge in translated.edges},
                translated.vertices,
                config,
            )
            cases.append(
                TranslatedCase(
                    case=f"amazon_{selector}_avg",
                    sweep="real_slice_avg_tile_work",
                    args=avg_args,
                    purpose=(
                        "Amazon-2008 real source slice translated to equal per-source "
                        "partition/tile work; preserves active-source count and total tile work approximately."
                    ),
                    translation="avg_tile_work",
                    selector=selector,
                    selector_start=selection.start,
                    raw_schedule=raw_schedule,
                    translated_schedule=translated_schedule,
                    raw_edges=len(edges),
                    translated_edges=translated.edge_count,
                    raw_max_edges_per_source=max_edges_per_source,
                )
            )

        raw_replay_proxy = raw_schedule.active_records * raw_schedule.touched_tiles
        striped_shape = single_partition_tile_count(raw_schedule)
        if striped_shape is not None and raw_replay_proxy > 65_536:
            partition, tile_count = striped_shape
            edges_per_source = max(1, int(round(len(edges) / source_count)))
            striped_edges = source_count * edges_per_source
            striped_args = (
                "--striped-source-tile-work",
                str(source_count),
                str(partition),
                str(tile_count),
                str(edges_per_source),
                "--print-tile-schedule",
            )
            if striped_edges <= config.batch_size_edges:
                translated = workload_for_args(striped_args, config)
                translated_schedule = schedule_for_edges(
                    translated.edges,
                    {edge.src for edge in translated.edges},
                    translated.vertices,
                    config,
                )
                cases.append(
                    TranslatedCase(
                        case=f"amazon_{selector}_striped",
                        sweep="real_slice_replay_fallback",
                        args=striped_args,
                        purpose=(
                            "Amazon-2008 large-frontier slice translated to striped source/tile work; "
                            "preserves active-source count, touched-tile count, and average edges per source "
                            "without exceeding current L0 batch capacity."
                        ),
                        translation="striped_avg_degree",
                        selector=selector,
                        selector_start=selection.start,
                        raw_schedule=raw_schedule,
                        translated_schedule=translated_schedule,
                        raw_edges=len(edges),
                        translated_edges=translated.edge_count,
                        raw_max_edges_per_source=max_edges_per_source,
                    )
                )

        if selector == "top512" or selector.startswith("densewin4096") or selector == "stride4096":
            aggregate_args = (
                "--partition-tile-work",
                *to_partition_specs(totals),
                "--print-tile-schedule",
            )
            aggregate_edges = len(edges)
            if aggregate_edges <= config.batch_size_edges:
                translated = workload_for_args(aggregate_args, config)
                translated_schedule = schedule_for_edges(
                    translated.edges,
                    {edge.src for edge in translated.edges},
                    translated.vertices,
                    config,
                )
                cases.append(
                    TranslatedCase(
                        case=f"amazon_{selector}_aggregate",
                        sweep="real_slice_aggregate_control",
                        args=aggregate_args,
                        purpose=(
                            "Amazon-2008 tile totals collapsed to one source; diagnostic control "
                            "that preserves tile work but intentionally removes replay pressure."
                        ),
                        translation="aggregate_one_source",
                        selector=selector,
                        selector_start=selection.start,
                        raw_schedule=raw_schedule,
                        translated_schedule=translated_schedule,
                        raw_edges=len(edges),
                        translated_edges=translated.edge_count,
                        raw_max_edges_per_source=max_edges_per_source,
                    )
                )

    for case in cases:
        coverage_status, coverage_notes = coverage_for(
            case.translated_schedule,
            case.translated_edges,
            config,
        )
        raw_replay = case.raw_schedule.active_records * case.raw_schedule.touched_tiles
        translated_replay = (
            case.translated_schedule.active_records * case.translated_schedule.touched_tiles
        )
        row = {
            "case": case.case,
            "sweep": case.sweep,
            "translation": case.translation,
            "selector": case.selector,
            "selector_start": "" if case.selector_start is None else case.selector_start,
            "raw_active_sources": case.raw_schedule.active_sources,
            "raw_edges": case.raw_edges,
            "raw_partition_count": len({entry.partition for entry in case.raw_schedule.entries}),
            "raw_touched_tiles": case.raw_schedule.touched_tiles,
            "raw_fast_path_tiles": case.raw_schedule.fast_path_tiles,
            "raw_full_path_tiles": case.raw_schedule.full_path_tiles,
            "raw_fallback_used": case.raw_schedule.fallback_used,
            "raw_clipped_ranges": case.raw_schedule.clipped_ranges,
            "raw_replay_proxy": raw_replay,
            "raw_avg_edges_per_source": case.raw_edges / max(1, case.raw_schedule.active_sources),
            "raw_max_edges_per_source": case.raw_max_edges_per_source,
            "raw_max_tile_work": max(
                (entry.tile_work for entry in case.raw_schedule.entries),
                default=0,
            ),
            "translated_edges": case.translated_edges,
            "translated_partition_count": len(
                {entry.partition for entry in case.translated_schedule.entries}
            ),
            "translated_touched_tiles": case.translated_schedule.touched_tiles,
            "translated_fast_path_tiles": case.translated_schedule.fast_path_tiles,
            "translated_full_path_tiles": case.translated_schedule.full_path_tiles,
            "translated_fallback_used": case.translated_schedule.fallback_used,
            "translated_clipped_ranges": case.translated_schedule.clipped_ranges,
            "translated_replay_proxy": translated_replay,
            "translated_max_tile_work": max(
                (entry.tile_work for entry in case.translated_schedule.entries),
                default=0,
            ),
            "edge_scale": case.translated_edges / max(1, case.raw_edges),
            "replay_scale": translated_replay / max(1, raw_replay),
            "coverage_status": coverage_status,
            "coverage_notes": coverage_notes,
            "args": " ".join(case.args),
            "purpose": case.purpose,
        }
        rows.append(row)

    summary = {
        "graph": str(graph),
        "graph_edges": stats.edge_count,
        "graph_vertices": stats.vertex_count,
        "graph_min_raw_vertex": stats.min_raw_vertex,
        "graph_max_raw_vertex": stats.max_raw_vertex,
        "graph_id_offset": stats.id_offset,
        "source_count_nonzero": len(stats.source_degrees),
        "max_source_degree": max(stats.source_degrees.values()),
        "cases": len(cases),
        "config": str(DEFAULT_CONFIG),
        "translation_note": (
            "Cases are host-runnable structural translations of real graph source slices; "
            "they do not replay the exact edge list in the HLS host."
        ),
    }
    return cases, rows, summary


def write_rows(path: Path, rows: list[dict[str, Any]]) -> None:
    keys = set(METRIC_FIELDS)
    for row in rows:
        keys.update(row)
    fieldnames = METRIC_FIELDS + sorted(keys.difference(METRIC_FIELDS))
    with path.open("w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        for row in rows:
            writer.writerow(row)


def write_json(path: Path, data: Any) -> None:
    path.write_text(json.dumps(data, indent=2, sort_keys=True) + "\n")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--graph", type=Path, default=DEFAULT_GRAPH)
    parser.add_argument("--config", type=Path, default=DEFAULT_CONFIG)
    parser.add_argument("--out-dir", type=Path, required=True)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    args.out_dir.mkdir(parents=True, exist_ok=True)
    config = load_config(args.config)
    stats = scan_graph(args.graph)
    selections = select_sources(stats)
    cases, rows, summary = translated_case_rows(args.graph, stats, config, selections)
    exact_cases, exact_rows = exact_slice_case_rows(
        args.graph,
        stats,
        config,
        selections,
        args.out_dir,
    )
    matrix = {
        "matrix": "phase3d_amazon_real_slices",
        "graph": str(args.graph),
        "config": str(args.config),
        "cases": [
            {
                "case": case.case,
                "sweep": case.sweep,
                "args": list(case.args),
                "purpose": case.purpose,
                "real_slice": {
                    "selector": case.selector,
                    "translation": case.translation,
                    "selector_start": case.selector_start,
                    "raw_edges": case.raw_edges,
                    "translated_edges": case.translated_edges,
                },
            }
            for case in cases
        ],
    }
    exact_matrix = {
        "matrix": "phase4a_amazon_exact_slices",
        "graph": str(args.graph),
        "config": str(args.config),
        "format": {
            "slice": "comment metadata plus whitespace rows: src dst weight diff",
            "src_dst": "zero_based",
        },
        "cases": [
            {
                "case": case.case,
                "sweep": case.sweep,
                "args": list(case.args),
                "purpose": case.purpose,
                "real_slice": {
                    "selector": case.selector,
                    "translation": "exact_edge_list",
                    "selector_start": case.selector_start,
                    "raw_edges": case.raw_edges,
                    "slice_path": str(case.slice_path),
                },
            }
            for case in exact_cases
        ],
    }
    summary["exact_cases"] = len(exact_cases)
    summary["exact_note"] = (
        "Exact cases replay zero-based real src/dst edge-list slices through "
        "the HLS host and simulator without avg/striped tile-work translation."
    )
    write_json(args.out_dir / "real_slice_summary.json", summary)
    write_json(args.out_dir / "real_slice_matrix.json", matrix)
    write_json(args.out_dir / "exact_slice_matrix.json", exact_matrix)
    write_rows(args.out_dir / "real_slice_metrics.csv", rows)
    write_rows(args.out_dir / "exact_slice_metrics.csv", exact_rows)
    print(
        "real_graph_slices: "
        f"graph_edges={stats.edge_count} graph_vertices={stats.vertex_count} "
        f"cases={len(cases)} exact_cases={len(exact_cases)} wrote={args.out_dir}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
