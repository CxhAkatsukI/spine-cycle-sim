#!/usr/bin/env python3
"""Run proposed ff13a67 full-word GraSU + ReGraph Full PageRank on SST-HBM."""

from __future__ import annotations

import argparse
import json
import math
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
from scripts.run_sst_grasu_regraph_hls_weighted import (  # noqa: E402
    HlsWeightedOracle,
    build_hls_weighted_oracle,
)
from spine_cycle_sim.experiments.grasu_addressing import (  # noqa: E402
    grasu_hbm_address_environment,
    partition_layout_footprints,
    validate_grasu_hbm_address_map,
    validate_partition_footprints,
)
from spine_cycle_sim.experiments.profile_capabilities import (  # noqa: E402
    AlgorithmCapability,
    CapabilityCatalog,
    load_capability_catalog,
)
from spine_cycle_sim.experiments.regraph_contracts import (  # noqa: E402
    expected_partitioned_source_cache_requests,
)
from spine_cycle_sim.experiments.shared_workloads import load_slice  # noqa: E402
from spine_cycle_sim.sst_binding import grasu_normalized_memory_binding  # noqa: E402
from spine_cycle_sim.sst_library import forced_sst_library_binding  # noqa: E402


DEFAULT_SST = Path("/data/feiyang/sst/bin/sst")
DEFAULT_PROFILE = (
    ROOT
    / "configs"
    / "architectures"
    / "grasu_regraph_weighted_pma_hls_proposed_pagerank_ff13a67.json"
)
DEFAULT_CAPABILITY_CATALOG = (
    ROOT / "configs" / "contracts" / "grasu_regraph_capabilities_v1.json"
)
DEFAULT_INITIAL = (
    ROOT / "tests" / "data" / "grasu_regraph_weighted_dynamic_initial.slice"
)
DEFAULT_UPDATE = (
    ROOT / "tests" / "data" / "grasu_regraph_weighted_dynamic_update.slice"
)


def require_hls_pagerank_capability(
    profile_path: Path, capability_catalog_path: Path
) -> tuple[CapabilityCatalog, AlgorithmCapability]:
    profile = json.loads(profile_path.read_text(encoding="utf-8"))
    catalog = load_capability_catalog(capability_catalog_path)
    profile_capability = catalog.profile(str(profile.get("profile_id", "")))
    if profile_capability.profile_path != profile_path.resolve():
        raise ValueError("HLS-equivalent PageRank capability profile path differs")
    capability = profile_capability.require("full_pagerank")
    if (
        profile_capability.comparison_role
        not in {"hls_equivalent_proposed", "normalized"}
        or profile_capability.handoff != "weighted_pma_to_axis_stream"
        or profile_capability.conversion_cost != "absent"
    ):
        raise ValueError("capability does not describe the proposed full-word path")
    return catalog, capability


def full_pagerank_oracle(
    vertices: int,
    edges: tuple[tuple[int, int, int], ...],
    damping: float,
    iterations: int,
) -> tuple[float, ...]:
    if vertices <= 0 or iterations <= 0 or not 0.0 < damping < 1.0:
        raise ValueError("invalid PageRank oracle dimensions")
    adjacency: list[list[int]] = [[] for _ in range(vertices)]
    for source, destination, _weight in edges:
        if not 0 <= source < vertices or not 0 <= destination < vertices:
            raise ValueError("PageRank edge is outside the graph")
        adjacency[source].append(destination)
    ranks = [1.0 / vertices] * vertices
    for _ in range(iterations):
        dangling = math.fsum(
            ranks[vertex] for vertex in range(vertices) if not adjacency[vertex]
        )
        base = (1.0 - damping) / vertices + damping * dangling / vertices
        next_ranks = [base] * vertices
        for source, destinations in enumerate(adjacency):
            if not destinations:
                continue
            contribution = damping * ranks[source] / len(destinations)
            for destination in destinations:
                next_ranks[destination] += contribution
        ranks = next_ranks
    return tuple(ranks)


def expected_source_cache_ledger(
    profile: dict[str, object], oracle: HlsWeightedOracle
) -> tuple[int, int, int]:
    """Return requests, response lines, and lane writes for sparse partitions."""

    params = profile["parameters"]
    memory = profile["memory"]
    assert isinstance(params, dict) and isinstance(memory, dict)
    iterations = int(params["pagerank_iterations"])
    partition_vertices = int(params["regraph_partition_vertices"])
    destination_partitions = (
        len(oracle.external_to_internal) + partition_vertices - 1
    ) // partition_vertices
    partition_sources: list[set[int]] = [
        set() for _ in range(destination_partitions)
    ]
    for source, destination, _ in oracle.final_internal_edges:
        partition_sources[destination // partition_vertices].add(source)
    requests = sum(
        expected_partitioned_source_cache_requests(
            sources,
            int(params["regraph_source_buffer_vertices"]),
            iterations,
        )
        for sources in partition_sources
    )
    state_bytes = int(params["pagerank_state_bytes_per_vertex"])
    vertices_per_beat = int(memory["data_width_bits"]) // 8 // state_bytes
    lines = (
        requests
        * int(params["regraph_source_buffer_vertices"])
        // vertices_per_beat
    )
    return requests, lines, lines * int(params["regraph_map_reduce_lanes"])


def validate_result(
    result: dict[str, object],
    profile: dict[str, object],
    oracle: HlsWeightedOracle,
    ranks_external: tuple[float, ...],
    downstream_sharing: str = "direct",
) -> None:
    params = profile["parameters"]
    memory = profile["memory"]
    assert isinstance(params, dict) and isinstance(memory, dict)
    iterations = int(params["pagerank_iterations"])
    vertices = len(oracle.external_to_internal)
    partition_vertices = int(params["regraph_partition_vertices"])
    destination_partitions = (vertices + partition_vertices - 1) // partition_vertices
    source_requests, source_lines, source_lane_writes = (
        expected_source_cache_ledger(profile, oracle)
    )
    rows = destination_partitions * partition_vertices // 2 * iterations
    bursts = destination_partitions * partition_vertices // 16 * iterations
    source_prepare_degree_reads = (vertices + 15) // 16
    reported_ranks = tuple(float(value) for value in result.get("ranks_external", []))
    external_max_abs_error = (
        max(abs(actual - expected) for actual, expected in zip(reported_ranks, ranks_external))
        if len(reported_ranks) == len(ranks_external)
        else math.inf
    )
    checks = {
        "success": result.get("success") is True,
        "mode": result.get("mode") == "grasu_regraph_hls_weighted_pagerank",
        "claim": result.get("claim_class")
        == "hls_equivalent_proposed_execution_driven_simulation",
        "timing": result.get("timing_evidence")
        == "execution_driven_sst_hbm_not_cycle_calibrated",
        "serial_order": result.get("pipeline_order")
        == "update_then_degree_barrier_then_pma_native_compute",
        "conversion_absent": result.get("conversion_cost_included") is False,
        "abi": result.get("pma_edge_abi") == params["grasu_pma_edge_abi"],
        "logical_updates": result.get("logical_updates") == oracle.logical_updates,
        "physical_updates": result.get("physical_updates") == oracle.physical_updates,
        "host_reorder": result.get("host_vertex_reorder") is True,
        "external_to_internal": result.get("external_to_internal")
        == list(oracle.external_to_internal),
        "internal_to_external": result.get("internal_to_external")
        == list(oracle.internal_to_external),
        "dual_oracle": result.get("correctness_mismatches") == 0
        and result.get("architecture_correctness_mismatches") == 0
        and result.get("mathematical_correctness_mismatches") == 0,
        "external_oracle": external_max_abs_error <= 1.0e-5,
        "update_state": result.get("update_state_mismatches") == 0,
        "degree_state": result.get("degree_state_mismatches") == 0,
        "degree_timed": result.get("degree_update_timing_included") is True,
        "degree_rmw": result.get("degree_updates_required")
        == oracle.physical_updates
        and result.get("degree_update_reads") == oracle.physical_updates
        and result.get("degree_update_writes") == oracle.physical_updates,
        "fixed_iterations": result.get("iterations") == iterations,
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
        "degree_reads": result.get("source_prepare_degree_reads")
        == source_prepare_degree_reads
        and result.get("degree_reads") == source_prepare_degree_reads + bursts,
        "live_edges": result.get("compute_live_edges")
        == len(oracle.final_external_edges) * iterations,
        "lanes": result.get("edge_lanes") == params["regraph_map_reduce_lanes"]
        and result.get("gather_banks") == params["regraph_map_reduce_lanes"],
        "source_requests": result.get("source_cache_requests") == source_requests,
        "source_lines": result.get("source_cache_lines") == source_lines,
        "source_lane_writes": result.get("source_cache_lane_writes")
        == source_lane_writes,
        "rows": result.get("gather_rows_emitted") == rows
        and result.get("merger_rows_consumed") == rows,
        "bursts": result.get("merger_bursts_emitted") == bursts
        and result.get("apply_input_bursts") == bursts
        and result.get("hbm_wrapper_input_bursts") == bursts,
        "request_ledger": result.get("expected_backend_requests")
        == result.get("backend_requests"),
    }
    failed = [name for name, passed in checks.items() if not passed]
    if failed:
        raise RuntimeError(
            "HLS-equivalent PageRank validation failed "
            f"({failed}); cycles={result.get('cycles')} "
            f"partitions={result.get('destination_partitions')} "
            f"pipelines={result.get('compute_pipelines')}"
        )


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--profile", type=Path, default=DEFAULT_PROFILE)
    parser.add_argument(
        "--capability-catalog", type=Path, default=DEFAULT_CAPABILITY_CATALOG
    )
    parser.add_argument("--workload", type=Path, default=DEFAULT_INITIAL)
    parser.add_argument("--update-workload", type=Path, default=DEFAULT_UPDATE)
    parser.add_argument(
        "--downstream-sharing", choices=("direct", "shared"), default=None
    )
    parser.add_argument("--out-dir", type=Path, required=True)
    parser.add_argument("--sst", type=Path, default=DEFAULT_SST)
    parser.add_argument("--lib-dir", type=Path, default=ROOT / "build" / "sst")
    parser.add_argument("--max-cycles", type=int, default=30_000_000)
    parser.add_argument("--no-build", action="store_true")
    parser.add_argument(
        "--reuse-result",
        action="store_true",
        help="Revalidate an existing result.json and DRAM directory without rerunning SST.",
    )
    parser.add_argument("--instantiate-all-hbm-channels", action="store_true")
    args = parser.parse_args()

    profile_path = args.profile.resolve()
    profile = json.loads(profile_path.read_text(encoding="utf-8"))
    expected_profiles = {
        "grasu_regraph_weighted_pma_hls_proposed_pagerank_ff13a67",
        "grasu_regraph_candidate10_normalized_hls_pagerank_v3",
        "grasu_regraph_candidate10_k1_multipart_pagerank_v4",
        "grasu_regraph_candidate10_k2_multipart_pagerank_v4",
        "grasu_regraph_candidate10_k4_multipart_pagerank_v4",
        "grasu_regraph_candidate10_k1_multipart_pagerank_packed_v5",
        "grasu_regraph_candidate10_k2_multipart_pagerank_packed_v5",
        "grasu_regraph_candidate10_k4_multipart_pagerank_packed_v5",
        "grasu_regraph_candidate10_k4_shared_multipart_pagerank_packed_v6",
        "grasu_regraph_candidate10_k1_multipart_pagerank_fullgraph_v7",
        "grasu_regraph_candidate10_k4_shared_multipart_pagerank_fullgraph_v7",
    }
    if profile.get("profile_id") not in expected_profiles:
        raise ValueError("runner requires a pinned HLS-derived PageRank profile")
    catalog, capability = require_hls_pagerank_capability(
        profile_path, args.capability_catalog.resolve()
    )
    params = profile["parameters"]
    memory = profile["memory"]
    profile_sharing = str(params.get("regraph_downstream_sharing", "direct"))
    downstream_sharing = args.downstream_sharing or profile_sharing
    if downstream_sharing != profile_sharing:
        raise ValueError("PageRank runner downstream sharing differs from profile")
    initial = load_slice(args.workload.resolve())
    update = load_slice(args.update_workload.resolve())
    oracle = build_hls_weighted_oracle(initial, update, 0)
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
    damping = float(params["pagerank_damping"])
    iterations = int(params["pagerank_iterations"])
    ranks_external = full_pagerank_oracle(
        initial.vertices, oracle.final_external_edges, damping, iterations
    )
    binding = grasu_normalized_memory_binding(
        profile, instantiate_all=args.instantiate_all_hbm_channels
    )
    kernel_clock = next(
        clock for clock in profile["clocks"] if clock["name"] == "kernel"
    )
    if not args.no_build and not args.reuse_result:
        subprocess.run(["make", "-C", "cpp/sst", "-j2"], cwd=ROOT, check=True)

    args.out_dir.mkdir(parents=True, exist_ok=True)
    result_path = (args.out_dir / "result.json").resolve()
    dram_dir = (args.out_dir / "dram").resolve()
    if args.reuse_result:
        if not result_path.is_file() or not dram_dir.is_dir():
            raise FileNotFoundError(
                "--reuse-result requires an existing result.json and DRAM directory"
            )
    else:
        result_path.unlink(missing_ok=True)
        shutil.rmtree(dram_dir, ignore_errors=True)
    env = os.environ.copy()
    env.update(
        {
            "GRASU_SST_MODE": "grasu_regraph_hls_weighted_pagerank",
            "GRASU_SST_CHANNELS": str(memory["channels"]),
            "GRASU_SST_ACTIVE_CHANNELS": ",".join(
                str(channel) for channel in binding.instantiated_channels
            ),
            "GRASU_SST_CHANNEL_BYTES": str(memory["channel_capacity_bytes"]),
            "GRASU_SST_WORKLOAD": str(args.workload.resolve()),
            "GRASU_SST_UPDATE_WORKLOAD": str(args.update_workload.resolve()),
            "GRASU_SST_OUTPUT": str(result_path),
            "GRASU_SST_DRAM_OUTPUT": str(dram_dir),
            "GRASU_SST_CORE_MHZ": str(kernel_clock["achieved_mhz"]),
            "GRASU_SST_MAX_CYCLES": str(args.max_cycles),
            "GRASU_SST_PAGERANK_ITERATIONS": str(iterations),
            "GRASU_SST_PAGERANK_DAMPING": str(damping),
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
            "GRASU_SST_DEGREE_CHANNEL": str(params["regraph_degree_channel"]),
            "GRASU_SST_DEGREE_FIFO_DEPTH": str(params["grasu_degree_fifo_depth"]),
            "GRASU_SST_DEGREE_REORDER_ENTRIES": str(
                params["grasu_degree_reorder_entries"]
            ),
            "GRASU_SST_PAGERANK_SOURCE_MAP_LATENCY": str(
                params["regraph_pagerank_source_map_latency"]
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
            "GRASU_SST_UPDATE_BASE": str(params["grasu_update_base_bytes"]),
            "GRASU_SST_ROW_OFFSET_BASE": str(
                params["grasu_row_offset_base_bytes"]
            ),
            "GRASU_SST_BINARY_BASE": str(params["grasu_binary_base_bytes"]),
            "GRASU_SST_PMA_BASE": str(params["grasu_pma_base_bytes"]),
            "GRASU_SST_VERTEX_STATE_BASE": str(
                params["grasu_vertex_state_base_bytes"]
            ),
            "GRASU_SST_SOURCE_STATE_BASE": str(
                params["grasu_source_state_base_bytes"]
            ),
            "GRASU_SST_SOURCE_STATE_BUFFER_STRIDE": str(
                params["grasu_source_state_buffer_stride_bytes"]
            ),
            "GRASU_SST_DEGREE_BASE": str(params["grasu_degree_base_bytes"]),
            "GRASU_SST_PARTITION_ADDRESS_STRIDE": str(
                params["grasu_partition_address_stride_bytes"]
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
    wall_seconds = 0.0
    if not args.reuse_result:
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
                f"HLS-equivalent PageRank SST failed with rc={completed.returncode}; "
                f"see {args.out_dir / 'sst.log'}"
            )
    result = json.loads(result_path.read_text(encoding="utf-8"))
    validate_result(
        result, profile, oracle, ranks_external, downstream_sharing
    )
    dram = load_dram_stats(dram_dir)
    if (
        dram["channels"] != len(binding.instantiated_channels)
        or dram["reads"] + dram["writes"] != result["backend_requests"]
    ):
        raise RuntimeError("HLS-equivalent PageRank DRAM ledger mismatch")
    manifest = {
        "schema_version": 1,
        "profile": str(profile_path),
        "profile_sha256": sha256(profile_path),
        "capability_catalog": str(catalog.manifest_path),
        "capability_catalog_sha256": catalog.manifest_sha256,
        "algorithm_capability": capability.manifest_record(),
        "workload": str(args.workload.resolve()),
        "workload_sha256": sha256(args.workload.resolve()),
        "update_workload": str(args.update_workload.resolve()),
        "update_workload_sha256": sha256(args.update_workload.resolve()),
        "sst_memory_binding": binding.as_manifest(),
        "physical_hbm_address_regions": address_regions,
        "sst_library_binding": sst_library,
        "sst_plugin_sha256": sst_library["plugin_sha256"],
        "sst_host_wall_seconds": wall_seconds,
        "sst_result_reused": args.reuse_result,
        "downstream_sharing": downstream_sharing,
        "command": command,
        "result": result,
        "dram": dram,
        "status": "PASS",
    }
    (args.out_dir / "manifest.json").write_text(
        json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    print(
        "PASS grasu_regraph_hls_pagerank_sst: "
        f"cycles={result['cycles']} update={result['update_cycles']} "
        f"compute={result['compute_cycles']} requests={result['backend_requests']}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
