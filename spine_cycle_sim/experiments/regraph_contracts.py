"""Shared validation contracts for the PMA-native ReGraph execution model."""

from __future__ import annotations

from itertools import chain
import math
from typing import Iterable


def expected_pagerank_source_cache_requests(
    vertices: int, source_buffer_vertices: int, iterations: int
) -> int:
    """Mirror the reader's one-window-ahead ping-pong prefetch contract."""

    if vertices <= 0 or source_buffer_vertices <= 0 or iterations <= 0:
        raise ValueError("source-cache request dimensions must be positive")
    source_windows = (vertices + source_buffer_vertices - 1) // source_buffer_vertices
    return (source_windows + 1) * iterations


def materialized_max_source(
    initial_records: Iterable[tuple[int, int, int, int]],
    update_records: Iterable[tuple[int, int, int, int]],
) -> int:
    """Return the largest source with a live differential edge instance."""

    counts: dict[tuple[int, int, int], int] = {}
    for src, dst, weight, diff in chain(initial_records, update_records):
        if src < 0 or dst < 0 or weight < 0 or diff == 0:
            raise ValueError("differential edge records must be valid and nonzero")
        key = (src, dst, weight)
        counts[key] = counts.get(key, 0) + diff
        if counts[key] < 0:
            raise ValueError(f"differential update deletes a missing edge: {key}")
    live_sources = [src for (src, _, _), count in counts.items() if count > 0]
    if not live_sources:
        raise ValueError("differential graph has no live edges")
    return max(live_sources)


def expected_weighted_source_cache_requests(
    max_live_source: int, source_buffer_vertices: int, supersteps: int
) -> int:
    """Mirror SSSP's source-driven scan plus one-window-ahead prefetch."""

    if max_live_source < 0 or source_buffer_vertices <= 0 or supersteps <= 0:
        raise ValueError("weighted source-cache request dimensions are invalid")
    highest_source_round = max_live_source // source_buffer_vertices
    return (highest_source_round + 2) * supersteps


def full_pagerank_rank_sum_tolerance(
    vertices: int, mathematical_max_abs_error: float
) -> float:
    """Bound an accurately summed rank vector using its per-vertex oracle error."""

    if vertices <= 0:
        raise ValueError("vertices must be positive")
    if (
        not math.isfinite(mathematical_max_abs_error)
        or mathematical_max_abs_error < 0.0
    ):
        raise ValueError("mathematical max absolute error must be finite and nonnegative")
    return 1.0e-5 + vertices * mathematical_max_abs_error


def float32_sequential_rank_sum_tolerance(
    vertices: int, accurate_sum_tolerance: float
) -> float:
    """Add the standard gamma_n bound for sequential float32 summation."""

    if vertices <= 0:
        raise ValueError("vertices must be positive")
    if not math.isfinite(accurate_sum_tolerance) or accurate_sum_tolerance < 0.0:
        raise ValueError("accurate sum tolerance must be finite and nonnegative")
    unit_roundoff = 2.0**-24
    accumulated = max(0, vertices - 1) * unit_roundoff
    if accumulated >= 1.0:
        raise ValueError("float32 sequential-sum bound is undefined at this size")
    gamma = accumulated / (1.0 - accumulated)
    return accurate_sum_tolerance + gamma * (1.0 + accurate_sum_tolerance)
