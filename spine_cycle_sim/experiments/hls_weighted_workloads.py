"""Frozen microbenchmarks for the ff13a67 weighted-PMA HLS contract."""

from __future__ import annotations

from dataclasses import dataclass

from .shared_workloads import SliceGraph, SliceRecord


@dataclass(frozen=True)
class HlsWeightedFixture:
    fixture_id: str
    role: str
    family: str
    graph: SliceGraph
    update: SliceGraph
    source: int = 0


def _graph(
    case_id: str, vertices: int, edges: tuple[tuple[int, int, int], ...]
) -> SliceGraph:
    return SliceGraph(
        case_id,
        vertices,
        tuple(sorted(SliceRecord(src, dst, weight, 1) for src, dst, weight in edges)),
    )


def _update(
    case_id: str, vertices: int, edges: tuple[tuple[int, int, int, int], ...]
) -> SliceGraph:
    return SliceGraph(
        f"{case_id}_update",
        vertices,
        tuple(sorted(SliceRecord(*edge) for edge in edges)),
    )


def _fixture(
    fixture_id: str,
    role: str,
    family: str,
    vertices: int,
    edges: tuple[tuple[int, int, int], ...],
    updates: tuple[tuple[int, int, int, int], ...],
) -> HlsWeightedFixture:
    return HlsWeightedFixture(
        fixture_id,
        role,
        family,
        _graph(fixture_id, vertices, edges),
        _update(fixture_id, vertices, updates),
    )


def hls_weighted_fixtures() -> tuple[HlsWeightedFixture, ...]:
    """Return disjoint update, topology, PMA, and source-window gates."""

    fixtures = [
        _fixture(
            "hls_insert_shortcut_v8",
            "calibration",
            "insert",
            8,
            ((0, 1, 8), (0, 3, 30), (1, 2, 5), (2, 3, 2)),
            ((0, 2, 1, 1),),
        ),
        _fixture(
            "hls_exact_delete_v8",
            "holdout",
            "delete",
            8,
            ((0, 1, 1), (0, 2, 2), (1, 3, 2), (2, 3, 2)),
            ((0, 1, 1, -1),),
        ),
        _fixture(
            "hls_weight_decrease_v8",
            "calibration",
            "weight_decrease",
            8,
            ((0, 1, 9), (0, 2, 2), (2, 1, 5), (1, 3, 2)),
            ((0, 1, 3, 1),),
        ),
        _fixture(
            "hls_weight_increase_v8",
            "holdout",
            "weight_increase",
            8,
            ((0, 1, 1), (0, 2, 3), (2, 1, 2), (1, 3, 2)),
            ((0, 1, 9, 1),),
        ),
        _fixture(
            "hls_mixed_update_v8",
            "holdout",
            "mixed",
            8,
            ((0, 1, 8), (0, 2, 2), (1, 3, 1), (2, 3, 8), (3, 4, 1)),
            (
                (0, 1, 3, 1),
                (0, 2, 10, 1),
                (1, 3, 1, -1),
                (2, 3, 4, 1),
                (2, 4, 2, 1),
            ),
        ),
        _fixture(
            "hls_chain_exact_four_hops_v8",
            "holdout",
            "four_hop_boundary",
            8,
            ((0, 1, 2), (1, 2, 2), (2, 3, 2), (3, 4, 2)),
            ((1, 2, 1, 1),),
        ),
    ]

    dense_edges = tuple((0, destination, 10) for destination in range(1, 25))
    dense_edges += tuple((source, 63, 1) for source in range(1, 25))
    dense_updates = tuple((0, destination, 1, 1) for destination in range(1, 9))
    dense_updates += tuple((0, destination, 10, -1) for destination in range(9, 13))
    dense_updates += tuple((0, destination, 2, 1) for destination in range(25, 33))
    fixtures.append(
        _fixture(
            "hls_dense_fanin_v64",
            "calibration",
            "dense_fanin",
            64,
            dense_edges,
            dense_updates,
        )
    )

    source_window_edges = tuple(
        (source, 4097 + source, 2) for source in range(4097)
    )
    fixtures.append(
        _fixture(
            "hls_source_window_4096_v8194",
            "holdout",
            "source_window_boundary",
            8194,
            source_window_edges,
            ((0, 4097, 1, 1),),
        )
    )

    multisegment_edges = tuple(
        (0, destination, 10) for destination in range(1, 49)
    )
    multisegment_updates = tuple(
        (0, destination, 5, 1) for destination in range(1, 18)
    )
    fixtures.append(
        _fixture(
            "hls_multisegment_variants_v128",
            "calibration",
            "pma_multisegment",
            128,
            multisegment_edges,
            multisegment_updates,
        )
    )
    fixtures.append(
        _fixture(
            "hls_reorder_tie_v8",
            "holdout",
            "reorder_tiebreak",
            8,
            ((0, 4, 10), (1, 5, 10), (2, 6, 10)),
            ((0, 4, 5, 1), (1, 5, 5, 1), (2, 6, 5, 1)),
        )
    )
    return tuple(fixtures)
