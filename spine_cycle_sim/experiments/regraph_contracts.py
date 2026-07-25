"""Shared validation contracts for the PMA-native ReGraph execution model."""

from __future__ import annotations

import math


def expected_source_cache_requests(
    vertices: int, source_buffer_vertices: int, iterations: int
) -> int:
    """Mirror the reader's one-window-ahead ping-pong prefetch contract."""

    if vertices <= 0 or source_buffer_vertices <= 0 or iterations <= 0:
        raise ValueError("source-cache request dimensions must be positive")
    source_windows = (vertices + source_buffer_vertices - 1) // source_buffer_vertices
    return (source_windows + 1) * iterations


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
