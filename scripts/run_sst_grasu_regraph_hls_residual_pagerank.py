#!/usr/bin/env python3
"""Run proposed ff13a67 GraSU + ReGraph residual PageRank on SST-HBM."""

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
from scripts.run_sst_grasu_regraph_hls_pagerank import (  # noqa: E402
    full_pagerank_oracle,
)
from scripts.run_sst_grasu_regraph_hls_weighted import (  # noqa: E402
    HlsWeightedOracle,
    build_hls_weighted_oracle,
)
from spine_cycle_sim.experiments.profile_capabilities import (  # noqa: E402
    AlgorithmCapability,
    CapabilityCatalog,
    load_capability_catalog,
)
from spine_cycle_sim.experiments.regraph_contracts import (  # noqa: E402
    expected_pagerank_source_cache_requests,
)
from spine_cycle_sim.experiments.shared_workloads import load_slice  # noqa: E402
from spine_cycle_sim.sst_binding import grasu_normalized_memory_binding  # noqa: E402


DEFAULT_SST = Path("/data/feiyang/sst/bin/sst")
DEFAULT_PROFILE = (
    ROOT
    / "configs"
    / "architectures"
    / "grasu_regraph_weighted_pma_hls_proposed_residual_pagerank_ff13a67.json"
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


def require_hls_residual_capability(
    profile_path: Path, capability_catalog_path: Path
) -> tuple[CapabilityCatalog, AlgorithmCapability]:
    profile = json.loads(profile_path.read_text(encoding="utf-8"))
    catalog = load_capability_catalog(capability_catalog_path)
    profile_capability = catalog.profile(str(profile.get("profile_id", "")))
    if profile_capability.profile_path != profile_path.resolve():
        raise ValueError("HLS-equivalent residual capability profile path differs")
    capability = profile_capability.require("thresholded_residual_pagerank")
    if (
        profile_capability.comparison_role != "hls_equivalent_proposed"
        or profile_capability.handoff != "weighted_pma_to_axis_stream"
        or profile_capability.conversion_cost != "absent"
    ):
        raise ValueError("capability does not describe the proposed full-word path")
    return catalog, capability


def validate_result(
    result: dict[str, object],
    profile: dict[str, object],
    oracle: HlsWeightedOracle,
    full_solution_external: tuple[float, ...],
) -> None:
    params = profile["parameters"]
    memory = profile["memory"]
    assert isinstance(params, dict) and isinstance(memory, dict)
    epsilon = float(params["pagerank_epsilon"])
    max_iterations = int(params["pagerank_residual_max_iterations"])
    iterations = int(result.get("iterations", -1))
    vertices = len(oracle.external_to_internal)
    partition_vertices = int(params["regraph_partition_vertices"])
    state_bytes = int(params["pagerank_state_bytes_per_vertex"])
    vertices_per_beat = int(memory["data_width_bits"]) // 8 // state_bytes
    source_requests = expected_pagerank_source_cache_requests(
        vertices, int(params["regraph_source_buffer_vertices"]), iterations
    )
    source_lines = (
        source_requests
        * int(params["regraph_source_buffer_vertices"])
        // vertices_per_beat
    )
    rows = partition_vertices // 2 * iterations
    bursts = partition_vertices // 16 * iterations
    ranks = tuple(float(value) for value in result.get("ranks_external", []))
    residuals = tuple(
        float(value) for value in result.get("residuals_external", [])
    )
    mathematical_error = (
        max(
            abs(actual - expected)
            for actual, expected in zip(ranks, full_solution_external)
        )
        if len(ranks) == len(full_solution_external)
        else math.inf
    )
    external_residual_l1 = (
        math.fsum(abs(value) for value in residuals)
        if len(residuals) == vertices
        else math.inf
    )
    checks = {
        "success": result.get("success") is True,
        "mode": result.get("mode")
        == "grasu_regraph_hls_weighted_residual_pagerank",
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
        "external_rank_oracle": mathematical_error <= 5.0 * epsilon,
        "external_residual": external_residual_l1 <= epsilon * 1.01,
        "converged": result.get("converged") is True
        and result.get("residual_bound_passed") is True
        and 0 < iterations <= max_iterations,
        "frontiers": len(result.get("frontier_in_sizes", [])) == iterations
        and len(result.get("frontier_out_sizes", [])) == iterations
        and result.get("frontier_out_sizes", [None])[-1] == 0,
        "active_edges": result.get("compute_active_edges")
        == result.get("expected_active_edges"),
        "update_state": result.get("update_state_mismatches") == 0,
        "degree_state": result.get("degree_state_mismatches") == 0,
        "degree_timed": result.get("degree_update_timing_included") is True,
        "degree_rmw": result.get("degree_updates_required")
        == oracle.physical_updates
        and result.get("degree_update_reads") == oracle.physical_updates
        and result.get("degree_update_writes") == oracle.physical_updates,
        "degree_reads": result.get("degree_reads") == vertices * iterations,
        "state_width": result.get("state_bytes_per_vertex") == state_bytes,
        "lanes": result.get("edge_lanes") == params["regraph_map_reduce_lanes"]
        and result.get("gather_banks") == params["regraph_map_reduce_lanes"],
        "source_requests": result.get("source_cache_requests") == source_requests,
        "source_lines": result.get("source_cache_lines") == source_lines,
        "source_lane_writes": result.get("source_cache_lane_writes")
        == source_lines * int(params["regraph_map_reduce_lanes"]),
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
            f"HLS-equivalent residual PageRank validation failed ({failed}): "
            f"{result}"
        )


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--profile", type=Path, default=DEFAULT_PROFILE)
    parser.add_argument(
        "--capability-catalog", type=Path, default=DEFAULT_CAPABILITY_CATALOG
    )
    parser.add_argument("--workload", type=Path, default=DEFAULT_INITIAL)
    parser.add_argument("--update-workload", type=Path, default=DEFAULT_UPDATE)
    parser.add_argument("--out-dir", type=Path, required=True)
    parser.add_argument("--sst", type=Path, default=DEFAULT_SST)
    parser.add_argument("--lib-dir", type=Path, default=ROOT / "build" / "sst")
    parser.add_argument("--max-cycles", type=int, default=100_000_000)
    parser.add_argument("--no-build", action="store_true")
    parser.add_argument("--instantiate-all-hbm-channels", action="store_true")
    args = parser.parse_args()

    profile_path = args.profile.resolve()
    profile = json.loads(profile_path.read_text(encoding="utf-8"))
    expected_profile = (
        "grasu_regraph_weighted_pma_hls_proposed_residual_pagerank_ff13a67"
    )
    if profile.get("profile_id") != expected_profile:
        raise ValueError("runner requires the pinned proposed residual profile")
    catalog, capability = require_hls_residual_capability(
        profile_path, args.capability_catalog.resolve()
    )
    params = profile["parameters"]
    memory = profile["memory"]
    initial = load_slice(args.workload.resolve())
    update = load_slice(args.update_workload.resolve())
    oracle = build_hls_weighted_oracle(initial, update, 0)
    damping = float(params["pagerank_damping"])
    epsilon = float(params["pagerank_epsilon"])
    max_iterations = int(params["pagerank_residual_max_iterations"])
    full_solution = full_pagerank_oracle(
        initial.vertices, oracle.final_external_edges, damping, 200
    )
    binding = grasu_normalized_memory_binding(
        profile, instantiate_all=args.instantiate_all_hbm_channels
    )
    kernel_clock = next(
        clock for clock in profile["clocks"] if clock["name"] == "kernel"
    )
    if not args.no_build:
        subprocess.run(["make", "-C", "cpp/sst", "-j2"], cwd=ROOT, check=True)

    args.out_dir.mkdir(parents=True, exist_ok=True)
    result_path = (args.out_dir / "result.json").resolve()
    dram_dir = (args.out_dir / "dram").resolve()
    result_path.unlink(missing_ok=True)
    shutil.rmtree(dram_dir, ignore_errors=True)
    env = os.environ.copy()
    env.update(
        {
            "GRASU_SST_MODE": "grasu_regraph_hls_weighted_residual_pagerank",
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
            "GRASU_SST_MAX_ROUNDS": str(max_iterations),
            "GRASU_SST_RESIDUAL_MAX_ITERATIONS": str(max_iterations),
            "GRASU_SST_PAGERANK_DAMPING": str(damping),
            "GRASU_SST_PAGERANK_EPSILON": str(epsilon),
            "GRASU_SST_CACHE_SEGMENTS_PER_HALF": str(
                params["grasu_cache_segments_per_cu"]
            ),
            "GRASU_SST_PARTITION_VERTICES": str(
                params["regraph_partition_vertices"]
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
    command = [
        str(args.sst.resolve()),
        f"--add-lib-path={args.lib_dir.resolve()}",
        str(ROOT / "sst" / "grasu_regraph_vertical.py"),
    ]
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
            f"HLS-equivalent residual PageRank SST failed with "
            f"rc={completed.returncode}; see {args.out_dir / 'sst.log'}"
        )
    result = json.loads(result_path.read_text(encoding="utf-8"))
    validate_result(result, profile, oracle, full_solution)
    dram = load_dram_stats(dram_dir)
    if (
        dram["channels"] != len(binding.instantiated_channels)
        or dram["reads"] + dram["writes"] != result["backend_requests"]
    ):
        raise RuntimeError("HLS-equivalent residual DRAM ledger mismatch")
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
        "sst_host_wall_seconds": wall_seconds,
        "command": command,
        "result": result,
        "dram": dram,
        "status": "PASS",
    }
    (args.out_dir / "manifest.json").write_text(
        json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    print(
        "PASS grasu_regraph_hls_residual_pagerank_sst: "
        f"cycles={result['cycles']} iterations={result['iterations']} "
        f"active_edges={result['compute_active_edges']} "
        f"requests={result['backend_requests']}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
