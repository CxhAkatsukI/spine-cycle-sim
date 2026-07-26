"""Pinned large real-edge PageRank runtime workload and capacity contract."""

from __future__ import annotations

import csv
import json
from pathlib import Path
from typing import Iterable, Mapping

from .real_small_batches import apply_explicit_weighted_updates
from .shared_workloads import (
    SliceGraph,
    SliceRecord,
    iter_matrix_market_edges,
    load_slice,
    sha256_file,
    write_slice,
)


LARGE_REAL_VERTEX_CAP = 65_536
LARGE_REAL_EXPECTED_VERTICES = 19_399
LARGE_REAL_EDGES = 50_000
LARGE_REAL_BATCH = 8
LARGE_REAL_PROFILE_SET = "candidate10_hls_v3"
SPINE_STRICT_FAMILY_CAPACITY = 16_384
SPINE_PARTITION_VERTICES = 1_048_576
SPINE_FAMILIES = 16
SPINE_HOT_SHARDS = 16


def _edge_weight(source: int, destination: int, salt: int) -> int:
    return 1 + ((source * 131 + destination * 17 + salt * 29) % 31)


def extract_large_real_slice(
    source_path: Path,
    *,
    case_id: str,
    vertices: int = LARGE_REAL_VERTEX_CAP,
    edge_limit: int = LARGE_REAL_EDGES,
    salt: int = 211,
) -> tuple[SliceGraph, tuple[tuple[int, int], ...]]:
    """Take a deterministic real-edge prefix under a compact-ID vertex cap."""

    if vertices <= 1 or edge_limit <= 0:
        raise ValueError("large real slice dimensions must be positive")
    external_to_local: dict[int, int] = {}
    edges: set[tuple[int, int]] = set()
    for external_source, external_destination in iter_matrix_market_edges(
        source_path
    ):
        if external_source == external_destination:
            continue
        missing = []
        for vertex in (external_source, external_destination):
            if vertex not in external_to_local and vertex not in missing:
                missing.append(vertex)
        if len(external_to_local) + len(missing) > vertices:
            continue
        for vertex in missing:
            external_to_local[vertex] = len(external_to_local)
        edge = (
            external_to_local[external_source],
            external_to_local[external_destination],
        )
        edges.add(edge)
        if len(edges) == edge_limit:
            break
    if len(edges) != edge_limit:
        raise ValueError(
            f"{source_path}: found {len(edges)} unique fitting edges, "
            f"need {edge_limit}"
        )
    records = tuple(
        SliceRecord(source, destination, _edge_weight(source, destination, salt), 1)
        for source, destination in sorted(edges)
    )
    mapping = tuple(
        sorted(
            ((local, external) for external, local in external_to_local.items()),
            key=lambda item: item[0],
        )
    )
    return SliceGraph(case_id, len(mapping), records), mapping


def build_large_real_update(
    graph: SliceGraph,
    *,
    mapped_vertices: int,
    batch_size: int = LARGE_REAL_BATCH,
) -> SliceGraph:
    if mapped_vertices <= batch_size or mapped_vertices > graph.vertices:
        raise ValueError("mapped vertex count cannot support the large update")
    existing = {(edge.src, edge.dst) for edge in graph.records}
    updates: list[SliceRecord] = []
    stride = max(1, mapped_vertices // batch_size)
    for index in range(batch_size):
        source = (index * stride) % mapped_vertices
        destination = (source + 17 + index * 131) % mapped_vertices
        while source == destination or (source, destination) in existing:
            destination = (destination + 1) % mapped_vertices
        existing.add((source, destination))
        updates.append(
            SliceRecord(
                source,
                destination,
                _edge_weight(source, destination, 223),
                1,
            )
        )
    return SliceGraph(
        f"{graph.case_id}_insert_u{batch_size}",
        graph.vertices,
        tuple(sorted(updates)),
    )


def spine_hot_hash(destination: int) -> int:
    value = destination & 0xFFFF_FFFF
    value ^= value >> 16
    value = (value * 0x7FEB_352D) & 0xFFFF_FFFF
    value ^= value >> 15
    value = (value * 0x846C_A68B) & 0xFFFF_FFFF
    value ^= value >> 16
    return value & 0xFFFF_FFFF


def classify_hot_destinations(
    graph: SliceGraph,
    update: SliceGraph,
    *,
    family_capacity: int = SPINE_STRICT_FAMILY_CAPACITY,
) -> dict[str, object]:
    """Mirror the HLS host indegree-descending hot/cold classifier."""

    final_graph = apply_explicit_weighted_updates(graph, update)
    indegree = [0] * final_graph.vertices
    for edge in final_graph.records:
        indegree[edge.dst] += 1
    cold = [0] * SPINE_FAMILIES
    hot = [0] * SPINE_HOT_SHARDS
    candidates = []
    for destination, degree in enumerate(indegree):
        if degree == 0:
            continue
        if degree > family_capacity:
            raise ValueError(
                f"destination {destination} indegree {degree} exceeds family cap"
            )
        family = min(destination // SPINE_PARTITION_VERTICES, SPINE_FAMILIES - 1)
        cold[family] += degree
        candidates.append((degree, destination))
    hot_vertices: list[int] = []
    for degree, destination in sorted(candidates, key=lambda item: (-item[0], item[1])):
        if all(count <= family_capacity for count in cold):
            break
        family = min(destination // SPINE_PARTITION_VERTICES, SPINE_FAMILIES - 1)
        shard = spine_hot_hash(destination) % SPINE_HOT_SHARDS
        cold[family] -= degree
        hot[shard] += degree
        hot_vertices.append(destination)
        if hot[shard] > family_capacity:
            raise ValueError(f"hot shard {shard} exceeds family capacity")
    if any(count > family_capacity for count in cold + hot):
        raise ValueError("HLS host classifier could not fit the final graph")
    return {
        "policy": "hls_host_indegree_desc_dst_asc_strict_l1_v1",
        "family_capacity": family_capacity,
        "hot_vertices": hot_vertices,
        "hot_vertex_count": len(hot_vertices),
        "cold_family_edges": cold,
        "hot_shard_edges": hot,
        "cold_edges": sum(cold),
        "hot_edges": sum(hot),
        "final_edges": len(final_graph.records),
    }


def _write_mapping(path: Path, mapping: Iterable[tuple[int, int]]) -> int:
    rows = tuple(mapping)
    with path.open("w", encoding="ascii", newline="") as stream:
        writer = csv.writer(stream, lineterminator="\n")
        writer.writerow(("local_id", "original_id"))
        writer.writerows(rows)
    return len(rows)


def _artifact(path: Path, root: Path) -> dict[str, object]:
    graph = load_slice(path)
    return {
        "path": str(path.resolve().relative_to(root.resolve())),
        "sha256": sha256_file(path),
        "case_id": graph.case_id,
        "vertices": graph.vertices,
        "records": len(graph.records),
    }


def build_large_real_pagerank_manifest(
    root: Path,
    *,
    source_path: Path,
    output_dir: Path,
    manifest_path: Path,
) -> dict[str, object]:
    root = root.resolve()
    source_path = source_path.resolve()
    output_dir = output_dir.resolve()
    output_dir.mkdir(parents=True, exist_ok=True)
    graph, mapping = extract_large_real_slice(
        source_path, case_id="real_amazon_2008_large_v19399_e50000"
    )
    update = build_large_real_update(graph, mapped_vertices=len(mapping))
    classification = classify_hot_destinations(graph, update)
    graph_path = output_dir / f"{graph.case_id}.slice"
    update_path = output_dir / f"{update.case_id}.slice"
    mapping_path = output_dir / f"{graph.case_id}.map.csv"
    expected_paths = {graph_path, update_path, mapping_path}
    for stale_path in output_dir.glob("real_amazon_2008_large_*"):
        if stale_path.is_file() and stale_path not in expected_paths:
            stale_path.unlink()
    write_slice(graph_path, graph)
    write_slice(update_path, update)
    mapping_rows = _write_mapping(mapping_path, mapping)
    run = {
        "run_id": "real_amazon_2008_large_e50000_insert_u8",
        "dataset_id": "amazon_2008",
        "dataset_kind": "real_large_slice",
        "input_scope": "real_large_slice",
        "role": "runtime_validation",
        "scenario": "insert",
        "source": 0,
        "graph": _artifact(graph_path, root),
        "update": _artifact(update_path, root),
        "mapping": {
            "path": str(mapping_path.relative_to(root)),
            "sha256": sha256_file(mapping_path),
            "rows": mapping_rows,
        },
        "user_mutations": len(update.records),
        "physical_records": len(update.records),
        "final_edges": len(graph.records) + len(update.records),
        "batch_size": len(update.records),
        "pattern": "source_scattered",
        "hot_vertices": classification["hot_vertices"],
        "hot_classification": {
            key: value
            for key, value in classification.items()
            if key != "hot_vertices"
        },
        "expected_spine_capacity_status": "PASS",
        "expected_grasu_capacity_status": "PASS",
    }
    manifest = {
        "schema_version": 1,
        "matrix_id": "hls_full_pagerank_real_large_runtime_20260726",
        "claim_class": "real_large_slice_runtime_input_contract",
        "input_scope": "real_large_slice",
        "required_profile_set": LARGE_REAL_PROFILE_SET,
        "source": {
            "dataset_id": "amazon_2008",
            "raw_path_hint": str(source_path),
            "raw_sha256": sha256_file(source_path),
            "extraction": "prefix_induced_compact_ids_unique_edges_v1",
        },
        "runtime_contract": {
            "vertices": graph.vertices,
            "normalized_vertex_cap": LARGE_REAL_VERTEX_CAP,
            "initial_edges": LARGE_REAL_EDGES,
            "batch_size": LARGE_REAL_BATCH,
            "algorithm": "full_pagerank",
            "iterations": 3,
            "host_runtime_limit_seconds_per_system": 1_800,
            "graph_and_update_bytes_identical_across_architectures": True,
            "correctness_gate": (
                "per_system_architecture_and_mathematical_oracles_plus_"
                "cross_system_rank_vector"
            ),
        },
        "runs": [run],
        "limitations": [
            "This is a 50000-edge, 19399-vertex real slice within the "
            "normalized 65536-vertex single-partition cap, not the complete "
            "Amazon-2008 graph.",
            "Hot destinations use the current HLS host classifier with a strict "
            "L1 family target so an occupied L0 can accept the timed batch.",
            "The Candidate10 normalized v3 profiles are required; routed HLS "
            "PPA/timing evidence is tracked separately from simulator timing.",
        ],
    }
    manifest_path.parent.mkdir(parents=True, exist_ok=True)
    manifest_path.write_text(
        json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="ascii"
    )
    validate_large_real_pagerank_manifest(root, manifest_path)
    return manifest


def validate_large_real_pagerank_manifest(
    root: Path, manifest_path: Path
) -> dict[str, object]:
    root = root.resolve()
    manifest = json.loads(manifest_path.resolve().read_text(encoding="ascii"))
    if manifest.get("matrix_id") != "hls_full_pagerank_real_large_runtime_20260726":
        raise ValueError("large real PageRank matrix identity mismatch")
    if manifest.get("required_profile_set") != LARGE_REAL_PROFILE_SET:
        raise ValueError("large real PageRank profile-set identity mismatch")
    runs = manifest.get("runs", [])
    if len(runs) != 1:
        raise ValueError("large real PageRank manifest requires exactly one run")
    run = runs[0]
    graph_path = root / run["graph"]["path"]
    update_path = root / run["update"]["path"]
    mapping_path = root / run["mapping"]["path"]
    for path, expected in (
        (graph_path, run["graph"]["sha256"]),
        (update_path, run["update"]["sha256"]),
        (mapping_path, run["mapping"]["sha256"]),
    ):
        if not path.is_file() or sha256_file(path) != expected:
            raise ValueError(f"large real artifact hash mismatch: {path}")
    graph = load_slice(graph_path)
    update = load_slice(update_path)
    if (
        graph.vertices != LARGE_REAL_EXPECTED_VERTICES
        or len(graph.records) != LARGE_REAL_EDGES
        or len(update.records) != LARGE_REAL_BATCH
    ):
        raise ValueError("large real shape mismatch")
    with mapping_path.open("r", encoding="ascii", newline="") as stream:
        mapping_rows = list(csv.DictReader(stream))
    if len(mapping_rows) != run["mapping"]["rows"]:
        raise ValueError("large real mapping row count mismatch")
    if [int(row["local_id"]) for row in mapping_rows] != list(
        range(len(mapping_rows))
    ):
        raise ValueError("large real mapping local IDs are not contiguous")
    final_graph = apply_explicit_weighted_updates(graph, update)
    if len(final_graph.records) != run["final_edges"]:
        raise ValueError("large real final edge count mismatch")
    classification = classify_hot_destinations(graph, update)
    if run.get("hot_vertices") != classification["hot_vertices"]:
        raise ValueError("large real hot vertex classification mismatch")
    expected_summary = {
        key: value for key, value in classification.items() if key != "hot_vertices"
    }
    if run.get("hot_classification") != expected_summary:
        raise ValueError("large real hot classification summary mismatch")
    if max(
        classification["cold_family_edges"]
        + classification["hot_shard_edges"]
    ) > SPINE_STRICT_FAMILY_CAPACITY:
        raise ValueError("large real final graph exceeds strict family capacity")
    return manifest


def evaluate_large_real_runtime_gate(
    manifest: Mapping[str, object], system_rows: Iterable[Mapping[str, object]]
) -> dict[str, object]:
    """Evaluate the per-system host-runtime contract without discarding data."""

    contract = manifest.get("runtime_contract")
    if not isinstance(contract, Mapping):
        raise ValueError("large real manifest lacks a runtime contract")
    limit = contract.get("host_runtime_limit_seconds_per_system")
    if isinstance(limit, bool) or not isinstance(limit, (int, float)) or limit <= 0:
        raise ValueError("large real runtime limit must be positive")
    observations = []
    seen: set[tuple[str, str]] = set()
    for row in system_rows:
        run_id = str(row.get("run_id", ""))
        system = str(row.get("system", ""))
        wall = row.get("host_wall_seconds")
        if (
            not run_id
            or system not in {"spine", "grasu_regraph"}
            or isinstance(wall, bool)
            or not isinstance(wall, (int, float))
            or wall <= 0
        ):
            raise ValueError("invalid large real runtime observation")
        identity = (run_id, system)
        if identity in seen:
            raise ValueError("duplicate large real runtime observation")
        seen.add(identity)
        observations.append(
            {
                "run_id": run_id,
                "system": system,
                "host_wall_seconds": float(wall),
                "limit_seconds": float(limit),
                "pass": float(wall) <= float(limit),
            }
        )
    expected = {
        (str(run["run_id"]), system)
        for run in manifest.get("runs", [])  # type: ignore[union-attr]
        for system in ("spine", "grasu_regraph")
    }
    if seen != expected:
        raise ValueError("large real runtime observations are incomplete")
    observations.sort(key=lambda row: (row["run_id"], row["system"]))
    failed = [
        {"run_id": row["run_id"], "system": row["system"]}
        for row in observations
        if not row["pass"]
    ]
    return {
        "status": "PASS" if not failed else "FAIL",
        "pass": not failed,
        "limit_seconds_per_system": float(limit),
        "observations": observations,
        "failed_systems": failed,
    }
