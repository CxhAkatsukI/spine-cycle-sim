"""Source-bound workloads for Spine candidate-10 HW/SST calibration."""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
from pathlib import Path
from typing import Callable, Iterable


FROZEN_HOST_SHA256 = (
    "a98b48b3b76980c7b27037490c38305329be87a5602c86838f5699551ef0fa65"
)
FROZEN_HOST_SPLIT_SHA256 = (
    "bb901978fa3d9821493cd9098f648199f8c52c7b2ed2f3914cd74068f3cea835"
)
MAX_VERTICES = 1 << 24
PARTITION_VERTICES = 1 << 20
PARTITIONS = 16
TILE_VERTICES = 65_536
TILES_PER_PARTITION = PARTITION_VERTICES // TILE_VERTICES
TINY_ACTIVE_THRESHOLD = 4_096
RANGE_TASK_CAPACITY = 65_536


@dataclass(frozen=True, order=True)
class Candidate10Edge:
    source: int
    destination: int
    weight: int
    diff: int = 1


@dataclass(frozen=True)
class Candidate10WorkloadCase:
    case_id: str
    evidence_case: str
    role: str
    generator: Callable[[], list[Candidate10Edge]]
    full_vertices: bool = False
    note: str = ""

    def edges(self) -> list[Candidate10Edge]:
        return sorted(self.generator())

    def vertices(self) -> int:
        if self.full_vertices:
            return MAX_VERTICES
        edges = self.edges()
        return max(
            1,
            1
            + max(
                (max(edge.source, edge.destination) for edge in edges),
                default=0,
            ),
        )


def generated_edges(edge_count: int) -> list[Candidate10Edge]:
    if not 0 < edge_count <= 131_072:
        raise ValueError("generated edge count must be in 1..131072")
    source_span = max(1, min(edge_count, PARTITION_VERTICES // 2))
    destination_base = max(source_span + 16, PARTITION_VERTICES // 8)
    if destination_base + source_span >= PARTITION_VERTICES:
        destination_base = PARTITION_VERTICES - source_span
    edges = []
    for index in range(edge_count):
        source = index % source_span
        partition = index % PARTITIONS
        destination = (
            partition * PARTITION_VERTICES
            + destination_base
            + index % source_span
        )
        edges.append(
            Candidate10Edge(source, destination, 1 + (index & 15), 1)
        )
    return edges


def dirty_boundary_edges(source_count: int) -> list[Candidate10Edge]:
    if not 0 < source_count <= 4_097:
        raise ValueError("dirty boundary source count must be in 1..4097")
    return [
        Candidate10Edge(
            source,
            (source + 1) % source_count,
            1 + (source & 15),
            1,
        )
        for source in range(source_count)
    ]


def sparse_source_edges(source_count: int) -> list[Candidate10Edge]:
    if source_count < 2:
        raise ValueError("sparse source count must be at least two")
    span = MAX_VERTICES - 1
    return [
        Candidate10Edge(
            (span * index) // (source_count - 1),
            (index % PARTITIONS) * PARTITION_VERTICES
            + 1
            + index // PARTITIONS,
            1 + (index & 15),
            1,
        )
        for index in range(source_count)
    ]


def duplicate_heavy_edges(raw_edge_count: int) -> list[Candidate10Edge]:
    if raw_edge_count < 4 or raw_edge_count % 4 or raw_edge_count > 131_072:
        raise ValueError("duplicate-heavy count must be a multiple of four")
    edges: list[Candidate10Edge] = []
    for group in range(raw_edge_count // 4):
        partition = group % PARTITIONS
        local = 1 + 2 * (group // PARTITIONS)
        keep = partition * PARTITION_VERTICES + local
        cancel = keep + 1
        source = group % 128
        edges.extend(
            (
                Candidate10Edge(source, keep, 11 + (group & 31), 1),
                Candidate10Edge(source, keep, 1 + (group & 15), 2),
                Candidate10Edge(source, cancel, 5, 1),
                Candidate10Edge(source, cancel, 7, -1),
            )
        )
    return edges


def tiny_edges() -> list[Candidate10Edge]:
    return [
        Candidate10Edge(0, 1, 5),
        Candidate10Edge(0, PARTITION_VERTICES + 1, 7),
        Candidate10Edge(1, 2, 3),
        Candidate10Edge(1, PARTITION_VERTICES + 2, 4),
        Candidate10Edge(3, 2 * PARTITION_VERTICES + 4, 6),
        Candidate10Edge(257, 258, 2),
        Candidate10Edge(257, PARTITION_VERTICES + 5, 8),
    ]


def sparse_wide_edges() -> list[Candidate10Edge]:
    return [
        Candidate10Edge(0, 1, 1),
        Candidate10Edge(0, (TILES_PER_PARTITION - 1) * TILE_VERTICES + 3, 2),
    ]


def fallback_forced_edges() -> list[Candidate10Edge]:
    active_count = TINY_ACTIVE_THRESHOLD + 1
    local = active_count + 1
    edges = [
        Candidate10Edge(0, tile * TILE_VERTICES + local, 1)
        for tile in range(TILES_PER_PARTITION)
    ]
    edges.extend(
        Candidate10Edge(source, source, 1)
        for source in range(1, active_count)
    )
    return edges


def tiny_mixed_fallback_edges() -> list[Candidate10Edge]:
    tiny_count = TINY_ACTIVE_THRESHOLD
    dense_count = TINY_ACTIVE_THRESHOLD + 1
    edges = [
        Candidate10Edge(0, 1 + index, 1 + (index & 31), 1)
        for index in range(tiny_count)
    ]
    edges.extend(
        Candidate10Edge(
            0,
            TILE_VERTICES + 1 + index,
            3 + (index & 31),
            1,
        )
        for index in range(dense_count)
    )
    return edges


def task_capacity_edges(exceed_capacity: bool = False) -> list[Candidate10Edge]:
    sources = RANGE_TASK_CAPACITY // TILES_PER_PARTITION
    edges = [
        Candidate10Edge(
            source,
            tile * TILE_VERTICES + 8_192 + source,
            1,
        )
        for source in range(sources)
        for tile in range(TILES_PER_PARTITION)
    ]
    if exceed_capacity:
        edges.append(Candidate10Edge(sources, 4_097, 1))
    return edges


def candidate10_workload_cases() -> tuple[Candidate10WorkloadCase, ...]:
    return (
        Candidate10WorkloadCase(
            "cal_zero", "zero_edge", "calibration", lambda: []
        ),
        Candidate10WorkloadCase(
            "cal_one", "one_edge", "calibration", lambda: generated_edges(1)
        ),
        Candidate10WorkloadCase(
            "cal_generated_128",
            "adjacent_l0",
            "calibration",
            lambda: generated_edges(128),
        ),
        Candidate10WorkloadCase(
            "cal_dirty_4096",
            "dirty_boundary_4096",
            "calibration",
            lambda: dirty_boundary_edges(4_096),
        ),
        Candidate10WorkloadCase(
            "holdout_current_value",
            "dirty_current_value",
            "holdout",
            lambda: [
                Candidate10Edge(0, 7, 1),
                Candidate10Edge(1, 8, 2),
                Candidate10Edge(2, 9, 3),
            ],
        ),
        Candidate10WorkloadCase(
            "holdout_tiny",
            "host_active_ack",
            "holdout",
            tiny_edges,
        ),
        Candidate10WorkloadCase(
            "holdout_sparse_wide",
            "sparse_wide",
            "holdout",
            sparse_wide_edges,
        ),
        Candidate10WorkloadCase(
            "holdout_sparse_sources_16",
            "sparse_sources",
            "holdout",
            lambda: sparse_source_edges(16),
            full_vertices=True,
        ),
        Candidate10WorkloadCase(
            "cal_duplicate_128",
            "duplicate_heavy",
            "calibration",
            lambda: duplicate_heavy_edges(128),
            note=(
                "Extra-edge calibration anchor; host preserves sorted "
                "duplicates for this case."
            ),
        ),
        Candidate10WorkloadCase(
            "holdout_fallback_4112",
            "fallback_forced",
            "holdout",
            fallback_forced_edges,
        ),
        Candidate10WorkloadCase(
            "holdout_tiny_mixed_fallback_8193",
            "tiny_mixed_fallback",
            "holdout",
            tiny_mixed_fallback_edges,
            note="One source spans one fast tile and one full tile.",
        ),
        Candidate10WorkloadCase(
            "stress_task_capacity_65536",
            "task_capacity_exact",
            "stress",
            task_capacity_edges,
        ),
    )


def slice_text(case: Candidate10WorkloadCase) -> str:
    lines = [
        "# spine_real_slice_version=1",
        f"# case={case.case_id}",
        f"# evidence_case={case.evidence_case}",
        f"# role={case.role}",
        f"# vertices={case.vertices()}",
        "# columns=src dst weight diff",
    ]
    lines.extend(
        f"{edge.source} {edge.destination} {edge.weight} {edge.diff}"
        for edge in case.edges()
    )
    return "\n".join(lines) + "\n"


def materialize_candidate10_workloads(
    out_dir: Path,
    *,
    roles: Iterable[str] = ("calibration", "holdout"),
) -> dict[str, object]:
    selected_roles = frozenset(roles)
    if not selected_roles or not selected_roles <= {
        "calibration",
        "holdout",
        "stress",
    }:
        raise ValueError("roles must select calibration, holdout, or stress")
    out_dir.mkdir(parents=True, exist_ok=True)
    rows = []
    for case in candidate10_workload_cases():
        if case.role not in selected_roles:
            continue
        path = out_dir / f"{case.case_id}.slice"
        payload = slice_text(case)
        path.write_text(payload, encoding="ascii")
        rows.append(
            {
                "case_id": case.case_id,
                "evidence_case": case.evidence_case,
                "role": case.role,
                "vertices": case.vertices(),
                "edges": len(case.edges()),
                "slice": str(path.resolve()),
                "slice_sha256": hashlib.sha256(payload.encode("ascii")).hexdigest(),
                "note": case.note,
            }
        )
    manifest = {
        "schema_version": 1,
        "claim": "frozen_candidate10_host_equivalent_workloads",
        "frozen_host_sha256": FROZEN_HOST_SHA256,
        "frozen_host_split_sha256": FROZEN_HOST_SPLIT_SHA256,
        "roles": sorted(selected_roles),
        "cases": rows,
    }
    (out_dir / "manifest.json").write_text(
        json.dumps(manifest, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return manifest
