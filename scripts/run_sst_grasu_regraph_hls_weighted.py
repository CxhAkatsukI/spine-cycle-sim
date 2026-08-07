#!/usr/bin/env python3
"""Run the ff13a67 weighted-PMA GraSU + ReGraph SST vertical slice."""

from __future__ import annotations

import argparse
from dataclasses import dataclass
import heapq
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.run_sst_grasu_regraph import load_dram_stats, sha256  # noqa: E402
from spine_cycle_sim.experiments.profile_capabilities import (  # noqa: E402
    AlgorithmCapability,
    CapabilityCatalog,
    load_capability_catalog,
)
from spine_cycle_sim.experiments.grasu_addressing import (  # noqa: E402
    grasu_hbm_address_environment,
    partition_layout_footprints,
    validate_grasu_hbm_address_map,
    validate_partition_footprints,
)
from spine_cycle_sim.experiments.host_memory import release_process_heap  # noqa: E402
from spine_cycle_sim.experiments.regraph_contracts import (  # noqa: E402
    expected_weighted_source_cache_requests,
)
from spine_cycle_sim.experiments.shared_workloads import (  # noqa: E402
    SliceGraph,
    load_slice,
)
from spine_cycle_sim.sst_binding import grasu_normalized_memory_binding  # noqa: E402
from spine_cycle_sim.sst_library import forced_sst_library_binding  # noqa: E402


DEFAULT_SST = Path("/data/feiyang/sst/bin/sst")
DEFAULT_PROFILE = (
    ROOT
    / "configs"
    / "architectures"
    / "grasu_regraph_weighted_pma_hls_sw_emu_ff13a67.json"
)
DEFAULT_CAPABILITY_CATALOG = (
    ROOT / "configs" / "contracts" / "grasu_regraph_capabilities_v1.json"
)
HLS_INFINITY = 0x7FFF_FFFE


@dataclass(frozen=True)
class HlsWeightedOracle:
    logical_updates: int
    physical_updates: int
    external_to_internal: tuple[int, ...]
    internal_to_external: tuple[int, ...]
    final_external_edges: tuple[tuple[int, int, int], ...]
    final_internal_edges: tuple[tuple[int, int, int], ...]
    external_distances: tuple[int, ...]
    source_internal: int
    minimum_supersteps: int


@dataclass(frozen=True)
class HlsWeightedRuntimeOracle:
    logical_updates: int
    physical_updates: int
    external_to_internal: tuple[int, ...]
    internal_to_external: tuple[int, ...]
    external_distances: tuple[int, ...]
    source_internal: int
    minimum_supersteps: int
    partition_vertices: int
    partition_max_sources: tuple[int | None, ...]


def compact_hls_weighted_oracle(
    oracle: HlsWeightedOracle, partition_vertices: int
) -> HlsWeightedRuntimeOracle:
    if partition_vertices <= 0:
        raise ValueError("partition_vertices must be positive")
    destination_partitions = (
        len(oracle.external_to_internal) + partition_vertices - 1
    ) // partition_vertices
    partition_max_sources: list[int | None] = [None] * destination_partitions
    for source, destination, _ in oracle.final_internal_edges:
        partition = destination // partition_vertices
        previous = partition_max_sources[partition]
        partition_max_sources[partition] = (
            source if previous is None else max(previous, source)
        )
    return HlsWeightedRuntimeOracle(
        logical_updates=oracle.logical_updates,
        physical_updates=oracle.physical_updates,
        external_to_internal=oracle.external_to_internal,
        internal_to_external=oracle.internal_to_external,
        external_distances=oracle.external_distances,
        source_internal=oracle.source_internal,
        minimum_supersteps=oracle.minimum_supersteps,
        partition_vertices=partition_vertices,
        partition_max_sources=tuple(partition_max_sources),
    )


def require_hls_weighted_capability(
    profile_path: Path,
    capability_catalog_path: Path,
    algorithm: str = "weighted_dynamic_sssp",
) -> tuple[CapabilityCatalog, AlgorithmCapability]:
    profile = json.loads(profile_path.read_text(encoding="utf-8"))
    profile_id = str(profile.get("profile_id", ""))
    catalog = load_capability_catalog(capability_catalog_path)
    profile_capability = catalog.profile(profile_id)
    if profile_capability.profile_path != profile_path.resolve():
        raise ValueError("weighted-HLS capability profile path does not match")
    if algorithm not in {"weighted_sssp", "weighted_dynamic_sssp"}:
        raise ValueError(f"unsupported weighted HLS capability: {algorithm}")
    capability = profile_capability.require(algorithm)
    if (
        profile_capability.comparison_role not in {"hls_sw_emu", "normalized"}
        or profile_capability.handoff != "weighted_pma_to_axis_stream"
        or profile_capability.conversion_cost != "absent"
    ):
        raise ValueError("capability does not describe the ff13a67 HLS path")
    return catalog, capability


def _dijkstra(
    vertices: int, edges: tuple[tuple[int, int, int], ...], source: int
) -> tuple[int, ...]:
    distances, _ = _dijkstra_with_minimum_supersteps(vertices, edges, source)
    return distances


def _dijkstra_with_minimum_supersteps(
    vertices: int, edges: tuple[tuple[int, int, int], ...], source: int
) -> tuple[tuple[int, ...], int]:
    """Compute exact distances and shortest-path hop depth in one traversal."""
    adjacency: list[list[tuple[int, int]]] = [[] for _ in range(vertices)]
    for src, dst, weight in edges:
        adjacency[src].append((dst, weight))
    unreachable = 1 << 63
    distances = [unreachable] * vertices
    hops = [unreachable] * vertices
    distances[source] = 0
    hops[source] = 0
    pending: list[tuple[int, int, int]] = [(0, 0, source)]
    while pending:
        distance, hop_count, vertex = heapq.heappop(pending)
        if distance != distances[vertex] or hop_count != hops[vertex]:
            continue
        for destination, weight in adjacency[vertex]:
            candidate = distance + weight
            candidate_hops = hop_count + 1
            if candidate < distances[destination] or (
                candidate == distances[destination]
                and candidate_hops < hops[destination]
            ):
                distances[destination] = candidate
                hops[destination] = candidate_hops
                heapq.heappush(
                    pending, (candidate, candidate_hops, destination)
                )
    return (
        tuple(HLS_INFINITY if value == unreachable else value for value in distances),
        max(1, max((value for value in hops if value != unreachable), default=0)),
    )


def _minimum_synchronous_supersteps(
    vertices: int, edges: tuple[tuple[int, int, int], ...], source: int
) -> int:
    _, minimum_supersteps = _dijkstra_with_minimum_supersteps(
        vertices, edges, source
    )
    return minimum_supersteps


def build_hls_weighted_oracle(
    initial: SliceGraph, update: SliceGraph, source_external: int
) -> HlsWeightedOracle:
    if initial.vertices != update.vertices or not 0 <= source_external < initial.vertices:
        raise ValueError("weighted-HLS workload dimensions are invalid")
    vertices = initial.vertices
    state: dict[tuple[int, int], int] = {}
    variants: list[set[tuple[int, int]]] = [set() for _ in range(vertices)]
    for edge in initial.records:
        key = (edge.src, edge.dst)
        if (
            edge.diff != 1
            or edge.weight <= 0
            or edge.weight > 0xFFF
            or key in state
        ):
            raise ValueError("invalid initial weighted-HLS edge")
        state[key] = edge.weight
        variants[edge.src].add((edge.dst, edge.weight))

    physical_counts = [0] * vertices
    for edge in update.records:
        key = (edge.src, edge.dst)
        old_weight = state.get(key)
        if abs(edge.diff) != 1 or edge.weight <= 0 or edge.weight > 0xFFF:
            raise ValueError("invalid weighted-HLS update")
        if edge.diff < 0:
            if old_weight != edge.weight:
                raise ValueError("weighted-HLS delete does not match live edge")
            physical_counts[edge.src] += 1
            del state[key]
            continue
        variants[edge.src].add((edge.dst, edge.weight))
        if old_weight is None:
            physical_counts[edge.src] += 1
            state[key] = edge.weight
        elif old_weight != edge.weight:
            physical_counts[edge.src] += 2
            state[key] = edge.weight
        else:
            raise ValueError("weighted-HLS insert already exists")

    def density(vertex: int) -> float:
        segments = (len(variants[vertex]) + 15) // 16
        return -1.0 if segments == 0 else physical_counts[vertex] / segments

    internal_to_external = tuple(
        sorted(range(vertices), key=lambda vertex: (-density(vertex), vertex))
    )
    external_to_internal_list = [0] * vertices
    for internal, external in enumerate(internal_to_external):
        external_to_internal_list[external] = internal
    external_to_internal = tuple(external_to_internal_list)
    external_edges = tuple(
        sorted((src, dst, weight) for (src, dst), weight in state.items())
    )
    internal_edges = tuple(
        sorted(
            (
                external_to_internal[src],
                external_to_internal[dst],
                weight,
            )
            for src, dst, weight in external_edges
        )
    )
    external_distances, minimum_supersteps = _dijkstra_with_minimum_supersteps(
        vertices, external_edges, source_external
    )
    return HlsWeightedOracle(
        logical_updates=len(update.records),
        physical_updates=sum(physical_counts),
        external_to_internal=external_to_internal,
        internal_to_external=internal_to_external,
        final_external_edges=external_edges,
        final_internal_edges=internal_edges,
        external_distances=external_distances,
        source_internal=external_to_internal[source_external],
        minimum_supersteps=minimum_supersteps,
    )


def validate_result(
    result: dict[str, object],
    profile: dict[str, object],
    oracle: HlsWeightedOracle | HlsWeightedRuntimeOracle,
    supersteps: int | None = None,
    downstream_sharing: str = "direct",
) -> None:
    params = profile["parameters"]
    assert isinstance(params, dict)
    supersteps = (
        int(params["hls_validation_supersteps"])
        if supersteps is None
        else supersteps
    )
    partition_vertices = int(params["regraph_partition_vertices"])
    source_buffer_vertices = int(params["regraph_source_buffer_vertices"])
    vertices = len(oracle.external_to_internal)
    destination_partitions = (vertices + partition_vertices - 1) // partition_vertices
    if isinstance(oracle, HlsWeightedRuntimeOracle):
        if (
            oracle.partition_vertices != partition_vertices
            or len(oracle.partition_max_sources) != destination_partitions
        ):
            raise ValueError(
                "compacted oracle partition geometry differs from profile"
            )
        partition_max_sources = oracle.partition_max_sources
    else:
        expanded_max_sources: list[int | None] = [None] * destination_partitions
        for source, destination, _ in oracle.final_internal_edges:
            partition = destination // partition_vertices
            previous = expanded_max_sources[partition]
            expanded_max_sources[partition] = (
                source if previous is None else max(previous, source)
            )
        partition_max_sources = tuple(expanded_max_sources)
    expected_source_requests = sum(
        expected_weighted_source_cache_requests(
            0 if max_source is None else max_source,
            source_buffer_vertices,
            supersteps,
        )
        for max_source in partition_max_sources
    )
    expected_source_lines = expected_source_requests * source_buffer_vertices // 16
    expected_rows = destination_partitions * partition_vertices // 2 * supersteps
    expected_bursts = destination_partitions * partition_vertices // 16 * supersteps
    checks = {
        "success": result.get("success") is True,
        "mode": result.get("mode") == "grasu_regraph_hls_weighted_sssp",
        "claim": result.get("claim_class")
        == "hls_sw_emu_aligned_execution_driven_simulation",
        "backend": result.get("backend") == "sst_memHierarchy_dramsim3",
        "serial_order": result.get("pipeline_order")
        == "update_then_barrier_then_pma_native_compute",
        "conversion_absent": result.get("conversion_cost_included") is False,
        "abi": result.get("pma_edge_abi") == params["grasu_pma_edge_abi"],
        "logical_updates": result.get("logical_updates") == oracle.logical_updates,
        "physical_updates": result.get("physical_updates")
        == oracle.physical_updates,
        "updates_alias": result.get("updates") == oracle.physical_updates,
        "physical_mix": result.get("update_inserts")
        + result.get("update_deletes")
        == oracle.physical_updates,
        "no_in_place_weight_change": result.get("update_weight_decreases") == 0
        and result.get("update_weight_increases") == 0,
        "pma_read_per_op": result.get("update_pma_reads")
        == oracle.physical_updates,
        "pma_write_per_op": result.get("update_pma_writes")
        == oracle.physical_updates,
        "host_reorder": result.get("host_vertex_reorder") is True,
        "external_to_internal": result.get("external_to_internal")
        == list(oracle.external_to_internal),
        "internal_to_external": result.get("internal_to_external")
        == list(oracle.internal_to_external),
        "source_external": result.get("source_external")
        == oracle.internal_to_external[oracle.source_internal],
        "source_internal": result.get("source_internal") == oracle.source_internal,
        "fixed_rounds": result.get("fixed_host_supersteps") is True
        and result.get("supersteps") == supersteps,
        "correctness": result.get("correctness_mismatches") == 0
        and result.get("architecture_correctness_mismatches") == 0
        and result.get("mathematical_correctness_mismatches") == 0,
        "external_oracle": result.get("distances_external")
        == list(oracle.external_distances),
        "lanes": result.get("edge_lanes") == params["regraph_map_reduce_lanes"]
        and result.get("gather_banks") == params["regraph_map_reduce_lanes"],
        "partitions": result.get("destination_partitions")
        == destination_partitions,
        "pipelines": result.get("compute_pipelines")
        == int(params.get("regraph_compute_pipelines", 1)),
        "downstream_sharing": result.get("downstream_sharing")
        == downstream_sharing,
        "downstream_parallelism": result.get(
            "max_parallel_downstream_partitions"
        )
        == (
            min(
                int(params.get("regraph_compute_pipelines", 1)),
                destination_partitions,
            )
            if downstream_sharing == "direct"
            else 1
        ),
        "source_requests": result.get("source_cache_requests")
        == expected_source_requests,
        "source_lines": result.get("source_cache_lines") == expected_source_lines,
        "source_lane_writes": result.get("source_cache_lane_writes")
        == expected_source_lines * params["regraph_map_reduce_lanes"],
        "rows": result.get("gather_rows_emitted") == expected_rows
        and result.get("merger_rows_consumed") == expected_rows,
        "bursts": result.get("merger_bursts_emitted") == expected_bursts
        and result.get("apply_input_bursts") == expected_bursts
        and result.get("hbm_wrapper_input_bursts") == expected_bursts,
    }
    failed = [name for name, passed in checks.items() if not passed]
    if failed:
        raise RuntimeError(
            f"weighted-HLS SST validation failed ({failed}); "
            f"cycles={result.get('cycles')} "
            f"partitions={result.get('destination_partitions')} "
            f"pipelines={result.get('compute_pipelines')}"
        )


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--profile", type=Path, default=DEFAULT_PROFILE)
    parser.add_argument(
        "--capability-catalog", type=Path, default=DEFAULT_CAPABILITY_CATALOG
    )
    parser.add_argument(
        "--workload",
        type=Path,
        default=ROOT / "tests" / "data" / "grasu_regraph_weighted_dynamic_initial.slice",
    )
    parser.add_argument(
        "--update-workload",
        type=Path,
        default=ROOT / "tests" / "data" / "grasu_regraph_weighted_dynamic_update.slice",
    )
    parser.add_argument("--source", type=int, default=0)
    parser.add_argument("--supersteps", type=int)
    parser.add_argument(
        "--downstream-sharing", choices=("direct", "shared"), default=None
    )
    parser.add_argument("--out-dir", type=Path, required=True)
    parser.add_argument("--sst", type=Path, default=DEFAULT_SST)
    parser.add_argument("--lib-dir", type=Path, default=ROOT / "build" / "sst")
    parser.add_argument("--max-cycles", type=int, default=30_000_000)
    parser.add_argument("--no-build", action="store_true")
    parser.add_argument("--instantiate-all-hbm-channels", action="store_true")
    parser.add_argument("--reuse-result", action="store_true")
    parser.add_argument(
        "--preflight-only",
        action="store_true",
        help="Persist the validated host oracle and exit before SST execution.",
    )
    parser.add_argument("--reused-wall-seconds", type=float)
    parser.add_argument("--reused-profile-sha256")
    args = parser.parse_args()
    if args.preflight_only and args.reuse_result:
        raise ValueError("preflight-only and result reuse are mutually exclusive")
    if args.reuse_result:
        if (
            args.reused_wall_seconds is None
            or args.reused_wall_seconds < 0
            or not args.reused_profile_sha256
        ):
            raise ValueError(
                "reused result requires nonnegative wall time and original profile SHA"
            )
        if not args.no_build:
            raise ValueError("reused result must not rebuild the SST plugin")
    elif args.reused_wall_seconds is not None or args.reused_profile_sha256:
        raise ValueError("reused result metadata requires --reuse-result")

    profile_path = args.profile.resolve()
    profile = json.loads(profile_path.read_text(encoding="utf-8"))
    expected_profile_ids = {
        "grasu_regraph_weighted_pma_hls_sw_emu_ff13a67",
        "grasu_regraph_candidate10_normalized_hls_weighted_v3",
        "grasu_regraph_candidate10_k1_multipart_weighted_v4",
        "grasu_regraph_candidate10_k2_multipart_weighted_v4",
        "grasu_regraph_candidate10_k4_multipart_weighted_v4",
        "grasu_regraph_candidate10_k1_multipart_weighted_packed_v5",
        "grasu_regraph_candidate10_k2_multipart_weighted_packed_v5",
        "grasu_regraph_candidate10_k4_multipart_weighted_packed_v5",
        "grasu_regraph_candidate10_k4_shared_multipart_weighted_packed_v6",
        "grasu_regraph_candidate10_k1_multipart_weighted_fullgraph_v7",
        "grasu_regraph_candidate10_k4_shared_multipart_weighted_fullgraph_v7",
    }
    if profile.get("profile_id") not in expected_profile_ids:
        raise ValueError("runner requires a pinned HLS-derived weighted profile")
    params = profile["parameters"]
    memory = profile["memory"]
    profile_sharing = str(params.get("regraph_downstream_sharing", "direct"))
    downstream_sharing = args.downstream_sharing or profile_sharing
    if downstream_sharing != profile_sharing:
        raise ValueError("weighted runner downstream sharing differs from profile")
    for evidence in profile.get("evidence", []):
        path = Path(evidence["path"])
        if not path.is_file() or sha256(path) != evidence["sha256"]:
            raise RuntimeError(f"weighted-HLS profile evidence mismatch: {path}")
    initial = load_slice(args.workload.resolve())
    update = load_slice(args.update_workload.resolve())
    input_vertices = initial.vertices
    input_records = len(initial.records)
    update_records = len(update.records)
    oracle = build_hls_weighted_oracle(initial, update, args.source)
    address_regions = None
    address_environment: dict[str, str] = {}
    if params.get("physical_address_map_id"):
        partition_vertices = int(params["regraph_partition_vertices"])
        destination_partitions = (
            initial.vertices + partition_vertices - 1
        ) // partition_vertices
        footprints = partition_layout_footprints(
            initial.records,
            update.records,
            initial.vertices,
            partition_vertices,
            oracle.external_to_internal,
            weighted_full_word=True,
        )
        validate_partition_footprints(params, footprints)
        address_regions = validate_grasu_hbm_address_map(
            params,
            int(memory["channel_capacity_bytes"]),
            destination_partitions,
            initial.vertices,
            oracle.physical_updates,
            footprints,
        )
        address_environment = grasu_hbm_address_environment(
            params, address_regions
        )
    capability_catalog, algorithm_capability = require_hls_weighted_capability(
        profile_path,
        args.capability_catalog.resolve(),
        "weighted_dynamic_sssp" if oracle.logical_updates else "weighted_sssp",
    )
    if profile["parameters"]["comparison_role"] == "hls_sw_emu":
        supersteps = args.supersteps or int(params["hls_validation_supersteps"])
        if supersteps != int(params["hls_validation_supersteps"]):
            raise ValueError(
                "ff13a67 evidence mode requires the pinned superstep count"
            )
        superstep_policy = "profile_pinned_hls_evidence"
    else:
        supersteps = args.supersteps or oracle.minimum_supersteps
        if supersteps < oracle.minimum_supersteps:
            raise ValueError(
                "normalized HLS-derived supersteps are below the oracle minimum"
            )
        superstep_policy = (
            "explicit" if args.supersteps is not None else "oracle_minimum"
        )
    binding = grasu_normalized_memory_binding(
        profile, instantiate_all=args.instantiate_all_hbm_channels
    )
    runtime_oracle = compact_hls_weighted_oracle(
        oracle, int(params["regraph_partition_vertices"])
    )
    del oracle
    del initial
    del update
    host_heap_trimmed = release_process_heap()
    kernel_clock = next(
        clock for clock in profile["clocks"] if clock["name"] == "kernel"
    )
    args.out_dir.mkdir(parents=True, exist_ok=True)
    preflight = {
        "schema_version": 1,
        "status": "PASS",
        "claim_class": "validated_host_oracle_preflight_not_simulated_performance",
        "profile": str(profile_path),
        "profile_sha256": sha256(profile_path),
        "capability_catalog": str(capability_catalog.manifest_path),
        "capability_catalog_sha256": capability_catalog.manifest_sha256,
        "algorithm_capability": algorithm_capability.manifest_record(),
        "workload": str(args.workload.resolve()),
        "workload_sha256": sha256(args.workload.resolve()),
        "update_workload": str(args.update_workload.resolve()),
        "update_workload_sha256": sha256(args.update_workload.resolve()),
        "source_external": args.source,
        "vertices": input_vertices,
        "directed_records": input_records,
        "logical_updates": runtime_oracle.logical_updates,
        "input_update_records": update_records,
        "physical_updates": runtime_oracle.physical_updates,
        "minimum_supersteps": runtime_oracle.minimum_supersteps,
        "selected_supersteps": supersteps,
        "superstep_policy": superstep_policy,
        "destination_partitions": len(runtime_oracle.partition_max_sources),
        "nonempty_destination_partitions": sum(
            value is not None for value in runtime_oracle.partition_max_sources
        ),
        "downstream_sharing": downstream_sharing,
        "sst_memory_binding": binding.as_manifest(),
        "physical_hbm_address_regions": address_regions,
        "host_oracle_storage": "compacted_before_sst_launch_v1",
        "host_heap_trimmed": host_heap_trimmed,
        "sst_execution_state_at_write": "not_started",
    }
    (args.out_dir / "preflight.json").write_text(
        json.dumps(preflight, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    if args.preflight_only:
        print(
            "PASS grasu_regraph_hls_weighted_preflight: "
            f"vertices={input_vertices} records={input_records} "
            f"supersteps={supersteps} partitions="
            f"{len(runtime_oracle.partition_max_sources)}"
        )
        return 0
    if not args.no_build:
        subprocess.run(["make", "-C", "cpp/sst", "-j2"], cwd=ROOT, check=True)

    result_path = (args.out_dir / "result.json").resolve()
    dram_dir = (args.out_dir / "dram").resolve()
    if not args.reuse_result:
        result_path.unlink(missing_ok=True)
        shutil.rmtree(dram_dir, ignore_errors=True)
    elif not result_path.is_file() or not dram_dir.is_dir():
        raise ValueError("completed result or DRAM evidence is missing")
    env = os.environ.copy()
    env.update(
        {
            "GRASU_SST_MODE": "grasu_regraph_hls_weighted_sssp",
            "GRASU_SST_CHANNELS": str(memory["channels"]),
            "GRASU_SST_ACTIVE_CHANNELS": ",".join(
                str(channel) for channel in binding.instantiated_channels
            ),
            "GRASU_SST_CHANNEL_BYTES": str(memory["channel_capacity_bytes"]),
            "GRASU_SST_WORKLOAD": str(args.workload.resolve()),
            "GRASU_SST_UPDATE_WORKLOAD": str(args.update_workload.resolve()),
            "GRASU_SST_SOURCE": str(args.source),
            "GRASU_SST_OUTPUT": str(result_path),
            "GRASU_SST_DRAM_OUTPUT": str(dram_dir),
            "GRASU_SST_CORE_MHZ": str(kernel_clock["achieved_mhz"]),
            "GRASU_SST_MAX_CYCLES": str(args.max_cycles),
            "GRASU_SST_NATIVE_SUPERSTEPS": str(supersteps),
            "GRASU_SST_CACHE_SEGMENTS_PER_HALF": str(
                params["grasu_cache_segments_per_cu"]
            ),
            "GRASU_SST_PARTITION_VERTICES": str(
                params["regraph_partition_vertices"]
            ),
            "GRASU_SST_COMPUTE_PIPELINES": str(
                params.get("regraph_compute_pipelines", 1)
            ),
            "GRASU_SST_SHARED_DOWNSTREAM": (
                "1" if downstream_sharing == "shared" else "0"
            ),
            "GRASU_SST_SHARDED_RUNTIME_PLACEMENT": (
                "1" if params.get("grasu_sharded_runtime_placement", False) else "0"
            ),
            "GRASU_SST_RUNTIME_CHANNEL_CAPACITY_BYTES": str(
                params.get(
                    "grasu_runtime_channel_capacity_bytes",
                    memory["channel_capacity_bytes"],
                )
            ),
            "GRASU_SST_SOURCE_BUFFER_VERTICES": str(
                params["regraph_source_buffer_vertices"]
            ),
            "GRASU_SST_SOURCE_CACHE_REQUEST_FIFO_DEPTH": str(
                params["regraph_source_cache_request_fifo_depth"]
            ),
            "GRASU_SST_SOURCE_CACHE_RESPONSE_FIFO_DEPTH": str(
                params["regraph_source_cache_response_fifo_depth"]
            ),
            "GRASU_SST_EDGE_LANES": str(params["regraph_map_reduce_lanes"]),
            "GRASU_SST_GATHER_BANKS": str(params["regraph_map_reduce_lanes"]),
            "GRASU_SST_AXIS_FIFO_DEPTH": str(
                params["regraph_pma_adapter_axis_fifo_depth"]
            ),
            "GRASU_SST_GATHER_BYPASS_DISTANCE": str(
                params["regraph_gather_bypass_distance"]
            ),
            "GRASU_SST_GATHER_PIPELINE_LATENCY": str(
                params["regraph_gather_pipeline_latency"]
            ),
            "GRASU_SST_SOURCE_STATE_CHANNEL": str(
                params["regraph_source_state_channel"]
            ),
            "GRASU_SST_SOURCE_STATE_MIRROR_CHANNEL": str(
                params["regraph_source_state_mirror_channel"]
            ),
            "GRASU_SST_APPLY_STATE_CHANNEL": str(
                params["regraph_apply_state_channel"]
            ),
            "GRASU_SST_GATHER_MERGER_FIFO_DEPTH": str(
                params["regraph_gather_merger_fifo_depth"]
            ),
            "GRASU_SST_MERGER_APPLY_FIFO_DEPTH": str(
                params["regraph_merger_apply_fifo_depth"]
            ),
            "GRASU_SST_APPLY_WRAPPER_FIFO_DEPTH": str(
                params["regraph_apply_wrapper_fifo_depth"]
            ),
            "GRASU_SST_MAX_PENDING_REQUESTS": str(
                memory["max_outstanding_per_port"]
            ),
            "GRASU_SST_MAX_OUTSTANDING_BURSTS": str(
                memory["max_outstanding_per_port"]
            ),
            "GRASU_SST_APPLY_REQUEST_WINDOW": str(
                params["regraph_apply_request_window"]
            ),
            "GRASU_SST_APPLY_PIPELINE_LATENCY": str(
                params["regraph_apply_pipeline_latency"]
            ),
            "GRASU_SST_APPLY_PIPELINE_CAPACITY": str(
                params["regraph_apply_pipeline_capacity"]
            ),
            "GRASU_SST_HBM_WRAPPER_PIPELINE_LATENCY": str(
                params["regraph_hbm_wrapper_pipeline_latency"]
            ),
            "GRASU_SST_HBM_WRAPPER_PIPELINE_CAPACITY": str(
                params["regraph_hbm_wrapper_pipeline_capacity"]
            ),
        }
    )
    env.update(address_environment)
    sst_library = forced_sst_library_binding(args.sst, args.lib_dir)
    command = [
        str(args.sst.resolve()),
        sst_library["command_option"],
        str(ROOT / "sst" / "grasu_regraph_vertical.py"),
    ]
    if args.reuse_result:
        wall_seconds = float(args.reused_wall_seconds)
        result_sha256_before_validation = sha256(result_path)
    else:
        started = time.monotonic()
        completed = subprocess.run(
            command,
            cwd=ROOT,
            env=env,
            check=False,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
        )
        wall_seconds = time.monotonic() - started
        (args.out_dir / "sst.log").write_text(completed.stdout, encoding="utf-8")
        if completed.returncode != 0:
            raise RuntimeError(
                f"weighted-HLS SST failed with rc={completed.returncode}; "
                f"see {args.out_dir / 'sst.log'}"
            )
        result_sha256_before_validation = None
    result = json.loads(result_path.read_text(encoding="utf-8"))
    validate_result(
        result, profile, runtime_oracle, supersteps, downstream_sharing
    )
    dram = load_dram_stats(dram_dir)
    if (
        dram["channels"] != len(binding.instantiated_channels)
        or dram["reads"] + dram["writes"] != result["backend_requests"]
    ):
        raise RuntimeError("weighted-HLS SST DRAM ledger mismatch")

    manifest = {
        "schema_version": 1,
        "profile": str(profile_path),
        "profile_sha256": sha256(profile_path),
        "capability_catalog": str(capability_catalog.manifest_path),
        "capability_catalog_sha256": capability_catalog.manifest_sha256,
        "algorithm_capability": algorithm_capability.manifest_record(),
        "workload": str(args.workload.resolve()),
        "workload_sha256": sha256(args.workload.resolve()),
        "update_workload": str(args.update_workload.resolve()),
        "update_workload_sha256": sha256(args.update_workload.resolve()),
        "source_external": args.source,
        "sst_memory_binding": binding.as_manifest(),
        "physical_hbm_address_regions": address_regions,
        "sst_library_binding": sst_library,
        "sst_plugin_sha256": sst_library["plugin_sha256"],
        "sst_host_wall_seconds": wall_seconds,
        "oracle": {
            "logical_updates": runtime_oracle.logical_updates,
            "physical_updates": runtime_oracle.physical_updates,
            "external_to_internal": list(runtime_oracle.external_to_internal),
            "external_distances": list(runtime_oracle.external_distances),
            "minimum_supersteps": runtime_oracle.minimum_supersteps,
        },
        "host_oracle_storage": "compacted_before_sst_launch_v1",
        "host_heap_trimmed": host_heap_trimmed,
        "preflight": preflight,
        "supersteps": supersteps,
        "superstep_policy": superstep_policy,
        "downstream_sharing": downstream_sharing,
        "command": command,
        "result": result,
        "dram": dram,
        "status": "PASS",
        "result_recovery": (
            {
                "classification": (
                    "completed_sst_result_revalidated_after_empty_partition_"
                    "source_prefetch_contract_fix"
                ),
                "original_profile_sha256": args.reused_profile_sha256,
                "current_profile_sha256": sha256(profile_path),
                "result_sha256_before_validation": (
                    result_sha256_before_validation
                ),
                "sst_rerun": False,
            }
            if args.reuse_result
            else None
        ),
    }
    (args.out_dir / "manifest.json").write_text(
        json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    print(
        "PASS grasu_regraph_hls_weighted_sst: "
        f"cycles={result['cycles']} update={result['update_cycles']} "
        f"compute={result['compute_cycles']} "
        f"logical={runtime_oracle.logical_updates} "
        f"physical={runtime_oracle.physical_updates} wall_s={wall_seconds:.3f}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
