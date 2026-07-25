"""Deterministic small differential batches for compact real graph slices."""

from __future__ import annotations

from dataclasses import dataclass
import heapq
import json
from pathlib import Path
from typing import Mapping

from .shared_workloads import SliceGraph, SliceRecord, load_slice, sha256_file, write_slice


REAL_BATCH_SIZE = 8
REAL_BATCH_SCENARIOS = ("insert", "delete", "weight_change")
HLS_FIXED_SSSP_ROUNDS = 4
HLS_INFINITY = 0x7FFFFFFE


@dataclass(frozen=True)
class RealSmallBatch:
    dataset_id: str
    scenario: str
    graph: SliceGraph
    update: SliceGraph
    user_mutations: int
    physical_records: int
    final_edges: int
    convergence_rounds: int


def _source_zero_edges(graph: SliceGraph) -> list[SliceRecord]:
    edges = sorted(edge for edge in graph.records if edge.src == 0 and edge.diff > 0)
    if len(edges) < REAL_BATCH_SIZE:
        raise ValueError(f"{graph.case_id} needs at least {REAL_BATCH_SIZE} source-0 edges")
    return edges


def _insert_batch(dataset_id: str, graph: SliceGraph) -> RealSmallBatch:
    live = {(edge.src, edge.dst) for edge in graph.records if edge.diff > 0}
    candidates = [
        vertex
        for vertex in range(128, graph.vertices)
        if vertex != 0 and (0, vertex) not in live
    ]
    if len(candidates) < REAL_BATCH_SIZE:
        raise ValueError(f"{graph.case_id} lacks deterministic insertion sinks")
    records = tuple(
        SliceRecord(0, destination, 1 + (index * 7) % 31, 1)
        for index, destination in enumerate(candidates[:REAL_BATCH_SIZE])
    )
    return _finish_batch(dataset_id, "insert", graph, records, REAL_BATCH_SIZE)


def _delete_batch(dataset_id: str, graph: SliceGraph) -> RealSmallBatch:
    records = tuple(
        SliceRecord(edge.src, edge.dst, edge.weight, -1)
        for edge in _source_zero_edges(graph)[:REAL_BATCH_SIZE]
    )
    return _finish_batch(dataset_id, "delete", graph, records, REAL_BATCH_SIZE)


def _weight_change_batch(dataset_id: str, graph: SliceGraph) -> RealSmallBatch:
    source_edges = _source_zero_edges(graph)
    decreases = [edge for edge in source_edges if edge.weight > 1][:4]
    if len(decreases) != 4:
        raise ValueError(f"{graph.case_id} lacks four positive weight decreases")
    decrease_keys = {(edge.src, edge.dst) for edge in decreases}
    increases = [
        edge for edge in reversed(source_edges)
        if (edge.src, edge.dst) not in decrease_keys
    ][:4]
    if len(increases) != 4:
        raise ValueError(f"{graph.case_id} lacks four disjoint weight increases")

    replacements: list[tuple[SliceRecord, SliceRecord]] = []
    for edge in decreases:
        replacements.append(
            (
                SliceRecord(edge.src, edge.dst, edge.weight, -1),
                SliceRecord(edge.src, edge.dst, max(1, edge.weight // 2), 1),
            )
        )
    for edge in increases:
        replacements.append(
            (
                SliceRecord(edge.src, edge.dst, edge.weight, -1),
                SliceRecord(edge.src, edge.dst, edge.weight + 17, 1),
            )
        )
    records = tuple(
        record
        for pair in sorted(replacements, key=lambda pair: (pair[0].src, pair[0].dst))
        for record in pair
    )
    return _finish_batch(
        dataset_id,
        "weight_change",
        graph,
        records,
        REAL_BATCH_SIZE,
    )


def apply_explicit_weighted_updates(
    graph: SliceGraph, update: SliceGraph
) -> SliceGraph:
    """Apply architecture-neutral exact-delete and absent-insert records."""

    if graph.vertices != update.vertices:
        raise ValueError("graph and update vertex counts differ")
    live: dict[tuple[int, int], int] = {}
    for edge in graph.records:
        if edge.diff <= 0 or (edge.src, edge.dst) in live:
            raise ValueError("base graph must contain unique positive edges")
        live[(edge.src, edge.dst)] = edge.weight
    for edge in update.records:
        key = (edge.src, edge.dst)
        if edge.diff == -1:
            if live.get(key) != edge.weight:
                raise ValueError(f"delete misses exact live edge {key}")
            del live[key]
        elif edge.diff == 1:
            if key in live:
                raise ValueError(f"insert collides with live edge {key}")
            live[key] = edge.weight
        else:
            raise ValueError("small-batch records must have diff +1 or -1")
    records = tuple(
        SliceRecord(src, dst, weight, 1)
        for (src, dst), weight in sorted(live.items())
    )
    return SliceGraph(f"{graph.case_id}+{update.case_id}", graph.vertices, records)


def sssp_convergence_rounds(graph: SliceGraph, source: int = 0) -> int:
    """Return synchronous relaxation rounds needed to equal Dijkstra."""

    adjacency: list[list[tuple[int, int]]] = [[] for _ in range(graph.vertices)]
    for edge in graph.records:
        if edge.diff > 0:
            adjacency[edge.src].append((edge.dst, edge.weight))
    oracle = [HLS_INFINITY] * graph.vertices
    oracle[source] = 0
    queue: list[tuple[int, int]] = [(0, source)]
    while queue:
        distance, vertex = heapq.heappop(queue)
        if distance != oracle[vertex]:
            continue
        for destination, weight in adjacency[vertex]:
            candidate = min(HLS_INFINITY, distance + weight)
            if candidate < oracle[destination]:
                oracle[destination] = candidate
                heapq.heappush(queue, (candidate, destination))

    synchronous = [HLS_INFINITY] * graph.vertices
    synchronous[source] = 0
    for round_number in range(1, 257):
        next_values = synchronous.copy()
        for edge in graph.records:
            if synchronous[edge.src] != HLS_INFINITY:
                next_values[edge.dst] = min(
                    next_values[edge.dst],
                    min(HLS_INFINITY, synchronous[edge.src] + edge.weight),
                )
        synchronous = next_values
        if synchronous == oracle:
            return round_number
    raise ValueError(f"{graph.case_id} does not converge within 256 rounds")


def _finish_batch(
    dataset_id: str,
    scenario: str,
    graph: SliceGraph,
    records: tuple[SliceRecord, ...],
    user_mutations: int,
) -> RealSmallBatch:
    update = SliceGraph(
        f"real_{dataset_id}_{scenario}_u{user_mutations}", graph.vertices, records
    )
    final_graph = apply_explicit_weighted_updates(graph, update)
    rounds = sssp_convergence_rounds(final_graph)
    if rounds > HLS_FIXED_SSSP_ROUNDS:
        raise ValueError(
            f"{update.case_id} needs {rounds} rounds, beyond the HLS contract"
        )
    return RealSmallBatch(
        dataset_id=dataset_id,
        scenario=scenario,
        graph=graph,
        update=update,
        user_mutations=user_mutations,
        physical_records=len(records),
        final_edges=len(final_graph.records),
        convergence_rounds=rounds,
    )


def build_real_small_batches(
    dataset_id: str, graph: SliceGraph
) -> tuple[RealSmallBatch, ...]:
    return (
        _insert_batch(dataset_id, graph),
        _delete_batch(dataset_id, graph),
        _weight_change_batch(dataset_id, graph),
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


def build_real_small_batch_manifest(
    root: Path,
    *,
    shared_manifest_path: Path,
    output_dir: Path,
    manifest_path: Path,
) -> dict[str, object]:
    root = root.resolve()
    shared_manifest_path = shared_manifest_path.resolve()
    shared = json.loads(shared_manifest_path.read_text(encoding="utf-8"))
    fixtures = {
        fixture["dataset_id"]: fixture
        for fixture in shared["fixtures"]
        if fixture["dataset_kind"] == "real_compact_slice"
    }
    runs: list[dict[str, object]] = []
    for dataset_id in ("amazon_2008", "web_google", "soc_flickr_und"):
        fixture = fixtures[dataset_id]
        graph_path = root / fixture["graph"]["path"]
        graph = load_slice(graph_path)
        for batch in build_real_small_batches(dataset_id, graph):
            update_path = output_dir / f"{batch.update.case_id}.slice"
            write_slice(update_path, batch.update)
            runs.append(
                {
                    "run_id": batch.update.case_id,
                    "dataset_id": dataset_id,
                    "dataset_kind": "real_compact_slice",
                    "role": "validation",
                    "scenario": batch.scenario,
                    "source": 0,
                    "graph": fixture["graph"],
                    "update": _artifact(update_path, root),
                    "user_mutations": batch.user_mutations,
                    "physical_records": batch.physical_records,
                    "final_edges": batch.final_edges,
                    "required_sssp_rounds": batch.convergence_rounds,
                    "hls_host_supersteps": HLS_FIXED_SSSP_ROUNDS,
                }
            )
    manifest = {
        "schema_version": 1,
        "matrix_id": "hls_weighted_real_small_batches_20260726",
        "claim_class": "hls_aligned_real_compact_small_batch_input_contract",
        "source_manifest": str(shared_manifest_path.relative_to(root)),
        "source_manifest_sha256": sha256_file(shared_manifest_path),
        "batch_contract": {
            "datasets": 3,
            "scenarios_per_dataset": 3,
            "user_mutations_per_batch": REAL_BATCH_SIZE,
            "scenarios": list(REAL_BATCH_SCENARIOS),
            "weight_change_encoding": "exact_delete_then_insert",
            "graph_and_update_bytes_identical_across_architectures": True,
            "correctness_gate": "architecture_oracle_and_uint64_dijkstra",
            "maximum_required_sssp_rounds": HLS_FIXED_SSSP_ROUNDS,
        },
        "runs": runs,
        "limitations": [
            "These are compact real-edge slices, not full real datasets.",
            (
                "Batches target source 0 direct edges or sink destinations to "
                "remain within the fixed four-round HLS profile."
            ),
            "Weight changes are one user mutation but two explicit differential records.",
            "No performance claim is made by this input manifest.",
        ],
    }
    manifest_path.parent.mkdir(parents=True, exist_ok=True)
    manifest_path.write_text(
        json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    return manifest


def validate_real_small_batch_manifest(
    root: Path, manifest_path: Path
) -> dict[str, object]:
    root = root.resolve()
    manifest_path = manifest_path.resolve()
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    source_path = root / manifest["source_manifest"]
    if sha256_file(source_path) != manifest["source_manifest_sha256"]:
        raise ValueError("shared workload source manifest hash mismatch")
    if len(manifest.get("runs", [])) != 9:
        raise ValueError("real small-batch manifest must contain nine runs")
    seen: set[tuple[str, str]] = set()
    for run in manifest["runs"]:
        key = (run["dataset_id"], run["scenario"])
        if key in seen:
            raise ValueError(f"duplicate real small-batch run {key}")
        seen.add(key)
        graph_path = root / run["graph"]["path"]
        update_path = root / run["update"]["path"]
        if sha256_file(graph_path) != run["graph"]["sha256"]:
            raise ValueError(f"graph hash mismatch for {run['run_id']}")
        if sha256_file(update_path) != run["update"]["sha256"]:
            raise ValueError(f"update hash mismatch for {run['run_id']}")
        graph = load_slice(graph_path)
        update = load_slice(update_path)
        expected = {
            batch.scenario: batch for batch in build_real_small_batches(run["dataset_id"], graph)
        }[run["scenario"]]
        if update != expected.update:
            raise ValueError(f"generated update mismatch for {run['run_id']}")
        if run["user_mutations"] != expected.user_mutations:
            raise ValueError(f"user mutation count mismatch for {run['run_id']}")
        if run["physical_records"] != expected.physical_records:
            raise ValueError(f"physical record count mismatch for {run['run_id']}")
        if run["required_sssp_rounds"] != expected.convergence_rounds:
            raise ValueError(f"SSSP round count mismatch for {run['run_id']}")
    expected_keys = {
        (dataset_id, scenario)
        for dataset_id in ("amazon_2008", "web_google", "soc_flickr_und")
        for scenario in REAL_BATCH_SCENARIOS
    }
    if seen != expected_keys:
        raise ValueError("real small-batch dataset/scenario coverage is incomplete")
    return manifest
