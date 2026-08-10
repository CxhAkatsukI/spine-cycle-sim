"""Deterministic large-batch workloads for paired Full PageRank sweeps."""

from __future__ import annotations

import json
from pathlib import Path

from .real_small_batches import apply_explicit_weighted_updates
from .shared_workloads import (
    SliceGraph,
    SliceRecord,
    load_slice,
    sha256_file,
    write_slice,
)


DENSE_SWEEP_VERTICES = 8192
DENSE_SWEEP_BATCH_SIZES = (8, 64, 512, 4096, 8192, 16384)
DENSE_SWEEP_PATTERNS = ("source_concentrated", "source_scattered")
SPINE_MAX_SORT_EDGES = 131_072
SPINE_CAPACITY_FAILURE = (
    "maintenance: Spine cold level hierarchy has no capacity-safe free target"
)
GRASU_DEGREE_REORDER_ENTRIES = 4_096


def build_dense_base_graph(vertices: int = DENSE_SWEEP_VERTICES) -> SliceGraph:
    if vertices < 1024:
        raise ValueError("dense sweep needs at least 1024 vertices")
    records = []
    for source in range(vertices):
        records.append(SliceRecord(source, (source + 1) % vertices, 1, 1))
    return SliceGraph("dense_batch_base_v8192", vertices, tuple(sorted(records)))


def _candidate_records(graph: SliceGraph, pattern: str) -> tuple[SliceRecord, ...]:
    live = {(edge.src, edge.dst) for edge in graph.records}
    candidates: list[SliceRecord] = []
    if pattern == "source_concentrated":
        for source in range(graph.vertices):
            for destination in range(graph.vertices):
                key = (source, destination)
                if source == destination or key in live:
                    continue
                weight = 1 + ((source * 17 + destination * 13) % 31)
                candidates.append(SliceRecord(source, destination, weight, 1))
                if len(candidates) >= max(DENSE_SWEEP_BATCH_SIZES):
                    return tuple(candidates)
    elif pattern == "source_scattered":
        round_index = 0
        while len(candidates) < max(DENSE_SWEEP_BATCH_SIZES):
            for source in range(graph.vertices):
                destination = (source + 2 + round_index * 131) % graph.vertices
                key = (source, destination)
                if source == destination or key in live:
                    continue
                weight = 1 + ((source * 7 + round_index * 11) % 31)
                candidates.append(SliceRecord(source, destination, weight, 1))
                if len(candidates) >= max(DENSE_SWEEP_BATCH_SIZES):
                    return tuple(candidates)
            round_index += 1
    else:
        raise ValueError(f"unsupported dense batch pattern: {pattern}")
    raise ValueError(f"could not generate enough {pattern} updates")


def build_dense_update(
    graph: SliceGraph, pattern: str, batch_size: int
) -> SliceGraph:
    if batch_size not in DENSE_SWEEP_BATCH_SIZES:
        raise ValueError(f"unsupported dense batch size: {batch_size}")
    candidates = _candidate_records(graph, pattern)
    records = tuple(sorted(candidates[:batch_size]))
    return SliceGraph(
        f"dense_{pattern}_u{batch_size}_v{graph.vertices}",
        graph.vertices,
        records,
    )


def _artifact(path: Path, root: Path) -> dict[str, object]:
    graph = load_slice(path)
    return {
        "path": str(path.resolve().relative_to(root.resolve())),
        "sha256": sha256_file(path),
        "case_id": graph.case_id,
        "vertices": graph.vertices,
        "records": len(graph.records),
    }


def _update_shape(update: SliceGraph) -> dict[str, object]:
    by_source: dict[int, int] = {}
    for edge in update.records:
        by_source[edge.src] = by_source.get(edge.src, 0) + 1
    return {
        "active_update_sources": len(by_source),
        "max_updates_per_source": max(by_source.values()),
        "mean_updates_per_active_source": len(update.records) / len(by_source),
    }


def build_dense_batch_manifest(
    root: Path, *, output_dir: Path, manifest_path: Path
) -> dict[str, object]:
    root = root.resolve()
    output_dir = output_dir.resolve()
    manifest_path = manifest_path.resolve()
    output_dir.mkdir(parents=True, exist_ok=True)
    graph = build_dense_base_graph()
    graph_path = output_dir / f"{graph.case_id}.slice"
    write_slice(graph_path, graph)
    graph_artifact = _artifact(graph_path, root)
    runs = []
    for pattern in DENSE_SWEEP_PATTERNS:
        for batch_size in DENSE_SWEEP_BATCH_SIZES:
            update = build_dense_update(graph, pattern, batch_size)
            update_path = output_dir / f"{update.case_id}.slice"
            write_slice(update_path, update)
            final_graph = apply_explicit_weighted_updates(graph, update)
            expected_spine_capacity_status = (
                "PASS"
                if batch_size <= SPINE_MAX_SORT_EDGES
                else "FAIL"
            )
            expected_grasu_capacity_status = (
                "PASS"
                if batch_size <= GRASU_DEGREE_REORDER_ENTRIES
                else "FAIL"
            )
            runs.append(
                {
                    "run_id": update.case_id,
                    "dataset_id": f"synthetic_dense_{pattern}",
                    "dataset_kind": "synthetic_dense_batch_sweep",
                    "role": "dense_sweep",
                    "scenario": "insert",
                    "pattern": pattern,
                    "batch_size": batch_size,
                    "source": 0,
                    "graph": graph_artifact,
                    "update": _artifact(update_path, root),
                    "user_mutations": batch_size,
                    "physical_records": batch_size,
                    "final_edges": len(final_graph.records),
                    "expected_spine_capacity_status":
                        expected_spine_capacity_status,
                    "expected_spine_capacity_reason": (
                        "within_max_sort_batch_capacity"
                        if expected_spine_capacity_status == "PASS"
                        else "max_sort_batch_capacity"
                    ),
                    "expected_grasu_capacity_status":
                        expected_grasu_capacity_status,
                    "expected_grasu_capacity_reason": (
                        "within_degree_reorder_entries"
                        if expected_grasu_capacity_status == "PASS"
                        else "degree_reorder_entries"
                    ),
                    "initial_edges_per_vertex": len(graph.records) / graph.vertices,
                    "inserted_edges_per_vertex": batch_size / graph.vertices,
                    **_update_shape(update),
                }
            )
    manifest = {
        "schema_version": 1,
        "matrix_id": "hls_full_pagerank_dense_batch_sweep_20260726",
        "claim_class": "synthetic_dense_batch_execution_input_contract",
        "input_scope": "synthetic_dense_batch_sweep",
        "batch_contract": {
            "algorithm": "full_pagerank",
            "patterns": list(DENSE_SWEEP_PATTERNS),
            "batch_sizes": list(DENSE_SWEEP_BATCH_SIZES),
            "vertices": graph.vertices,
            "initial_edges": len(graph.records),
            "spine_max_sort_edges": SPINE_MAX_SORT_EDGES,
            "grasu_degree_reorder_entries": GRASU_DEGREE_REORDER_ENTRIES,
            "updates_are_insertions": True,
            "graph_and_update_bytes_identical_across_architectures": True,
            "correctness_gate": (
                "per_system_architecture_and_mathematical_oracles_plus_"
                "cross_system_rank_vector"
            ),
        },
        "runs": runs,
        "limitations": [
            "The sweep is synthetic and isolates batch size and source concentration.",
            "It is not a full real-dataset performance result.",
            "All current endpoints are within Spine MAX_SORT_N=131072. The "
            "capacity-safe selector may skip undersized L1-L3 targets, so 16384 "
            "concentrated updates are a timing row rather than a capacity failure.",
            "The proposed GraSU PageRank degree-maintenance scoreboard has 4096 "
            "entries; larger batches are profile-capacity results until a windowed "
            "degree HLS implementation is supplied.",
            "GraSU/ReGraph PageRank remains an HLS-equivalent proposed profile.",
        ],
    }
    manifest_path.parent.mkdir(parents=True, exist_ok=True)
    manifest_path.write_text(
        json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    return manifest


def validate_dense_batch_manifest(
    root: Path, manifest_path: Path
) -> dict[str, object]:
    root = root.resolve()
    manifest = json.loads(manifest_path.resolve().read_text(encoding="utf-8"))
    if manifest.get("matrix_id") != "hls_full_pagerank_dense_batch_sweep_20260726":
        raise ValueError("dense batch matrix identity mismatch")
    contract = manifest.get("batch_contract", {})
    if contract.get("patterns") != list(DENSE_SWEEP_PATTERNS):
        raise ValueError("dense batch pattern axis mismatch")
    if contract.get("batch_sizes") != list(DENSE_SWEEP_BATCH_SIZES):
        raise ValueError("dense batch size axis mismatch")
    runs = manifest.get("runs", [])
    if len(runs) != len(DENSE_SWEEP_PATTERNS) * len(DENSE_SWEEP_BATCH_SIZES):
        raise ValueError("dense batch manifest has incomplete coverage")

    expected_graph = build_dense_base_graph()
    seen: set[tuple[str, int]] = set()
    for run in runs:
        key = (str(run["pattern"]), int(run["batch_size"]))
        if key in seen:
            raise ValueError(f"duplicate dense batch run: {key}")
        seen.add(key)
        graph_path = root / run["graph"]["path"]
        update_path = root / run["update"]["path"]
        if sha256_file(graph_path) != run["graph"]["sha256"]:
            raise ValueError(f"dense graph hash mismatch for {run['run_id']}")
        if sha256_file(update_path) != run["update"]["sha256"]:
            raise ValueError(f"dense update hash mismatch for {run['run_id']}")
        graph = load_slice(graph_path)
        update = load_slice(update_path)
        expected_update = build_dense_update(graph, *key)
        if graph != expected_graph or update != expected_update:
            raise ValueError(f"dense generated workload mismatch for {run['run_id']}")
        final_graph = apply_explicit_weighted_updates(graph, update)
        if int(run["final_edges"]) != len(final_graph.records):
            raise ValueError(f"dense final edge count mismatch for {run['run_id']}")
        expected_capacity_status = (
            "PASS"
            if key[1] <= int(contract["spine_max_sort_edges"])
            else "FAIL"
        )
        if run.get("expected_spine_capacity_status") != expected_capacity_status:
            raise ValueError(f"dense capacity expectation mismatch for {run['run_id']}")
        expected_grasu_status = (
            "PASS"
            if key[1] <= int(contract["grasu_degree_reorder_entries"])
            else "FAIL"
        )
        if run.get("expected_grasu_capacity_status") != expected_grasu_status:
            raise ValueError(
                f"GraSU dense capacity expectation mismatch for {run['run_id']}"
            )
        expected_shape = _update_shape(update)
        if any(run[name] != value for name, value in expected_shape.items()):
            raise ValueError(f"dense update shape mismatch for {run['run_id']}")
        if (
            int(run["user_mutations"]) != key[1]
            or int(run["physical_records"]) != key[1]
        ):
            raise ValueError(f"dense batch count mismatch for {run['run_id']}")

    expected_keys = {
        (pattern, batch_size)
        for pattern in DENSE_SWEEP_PATTERNS
        for batch_size in DENSE_SWEEP_BATCH_SIZES
    }
    if seen != expected_keys:
        raise ValueError("dense batch axis coverage mismatch")
    return manifest


def validate_spine_dense_capacity_failure(
    run: dict[str, object], result: dict[str, object]
) -> list[str]:
    checks = {
        "expected_failure": run.get("expected_spine_capacity_status") == "FAIL",
        "success": result.get("success") is False,
        "mode": result.get("mode") == "spine_pagerank",
        "dynamic": result.get("dynamic_update") is True,
        "failure": result.get("failure") == SPINE_CAPACITY_FAILURE,
        "vertices": result.get("vertices") == run["graph"]["vertices"],
        "initial_edges": result.get("initial_edges") == run["graph"]["records"],
        "update_edges": result.get("update_edges") == run["physical_records"],
        "final_edges": result.get("materialized_snapshot_edges")
        == run["final_edges"],
        "target_level": result.get("maintenance_target_level") == -1,
        "overflow": result.get("maintenance_logical_overflow_events") == 1,
        "maintenance_only": int(result.get("maintenance_cycles", 0)) > 0
        and result.get("maintenance_persisted_edges") == 0
        and result.get("compute_backend_requests") == 0
        and result.get("pagerank_completed_iterations") == 0,
    }
    return [name for name, passed in checks.items() if not passed]


def validate_grasu_dense_capacity_rejection(
    run: dict[str, object], profile: dict[str, object]
) -> list[str]:
    parameters = profile.get("parameters", {})
    if not isinstance(parameters, dict):
        return ["profile_parameters"]
    entries = parameters.get("grasu_degree_reorder_entries")
    checks = {
        "expected_failure": run.get("expected_grasu_capacity_status") == "FAIL",
        "profile_entries": entries == GRASU_DEGREE_REORDER_ENTRIES,
        "batch_exceeds_entries": int(run.get("physical_records", 0))
        > GRASU_DEGREE_REORDER_ENTRIES,
        "reason": run.get("expected_grasu_capacity_reason")
        == "degree_reorder_entries",
    }
    return [name for name, passed in checks.items() if not passed]
