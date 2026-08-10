#!/usr/bin/env python3
"""Run profile-pinned GraSU + PMA-native ReGraph Full PageRank on SST-HBM."""

from __future__ import annotations

import argparse
import hashlib
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

from spine_cycle_sim.sst_binding import grasu_normalized_memory_binding  # noqa: E402
from spine_cycle_sim.sst_library import forced_sst_library_binding  # noqa: E402
from spine_cycle_sim.experiments.regraph_contracts import (  # noqa: E402
    expected_pagerank_source_cache_requests,
    float32_sequential_rank_sum_tolerance,
    full_pagerank_rank_sum_tolerance,
)


DEFAULT_SST = Path("/data/feiyang/sst/bin/sst")
DEFAULT_PROFILE = (
    ROOT
    / "configs"
    / "architectures"
    / "grasu_regraph_normalized_pagerank_spine23.json"
)
DEFAULT_WORKLOAD = (
    ROOT / "tests" / "data" / "grasu_regraph_pagerank_initial.slice"
)


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for block in iter(lambda: source.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def load_dram_stats(dram_dir: Path) -> dict[str, int | float]:
    totals: dict[str, int | float] = {
        "channels": 0,
        "reads": 0,
        "writes": 0,
        "activates": 0,
        "precharges": 0,
        "total_energy_pj": 0.0,
    }
    paths = sorted(dram_dir.glob("channel*/dramsim3.json"))
    if not paths:
        raise ValueError(f"no DRAMSim3 JSON found under {dram_dir}")
    for path in paths:
        payload = json.loads(path.read_text(encoding="utf-8"))
        if len(payload) != 1:
            raise ValueError(f"expected one DRAM channel record in {path}")
        row = next(iter(payload.values()))
        totals["channels"] += 1
        totals["reads"] += int(row["num_reads_done"])
        totals["writes"] += int(row["num_writes_done"])
        totals["activates"] += int(row["num_act_cmds"])
        totals["precharges"] += int(row["num_pre_cmds"])
        totals["total_energy_pj"] += float(row["total_energy"])
    return totals


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--profile", type=Path, default=DEFAULT_PROFILE)
    parser.add_argument("--workload", type=Path, default=DEFAULT_WORKLOAD)
    parser.add_argument("--iterations", type=int, default=3)
    parser.add_argument("--damping", type=float)
    parser.add_argument("--out-dir", type=Path, required=True)
    parser.add_argument("--sst", type=Path, default=DEFAULT_SST)
    parser.add_argument("--lib-dir", type=Path, default=ROOT / "build" / "sst")
    parser.add_argument("--max-cycles", type=int, default=20_000_000)
    parser.add_argument(
        "--smoke",
        action="store_true",
        help="Use a 16-word partition and label the run component validation.",
    )
    parser.add_argument("--no-build", action="store_true")
    parser.add_argument(
        "--instantiate-all-hbm-channels",
        action="store_true",
        help="instantiate idle SST HBM controllers for equivalence or energy runs",
    )
    args = parser.parse_args()
    if args.iterations <= 0 or args.max_cycles <= 0:
        raise ValueError("iterations and max-cycles must be positive")

    profile_path = args.profile.resolve()
    workload_path = args.workload.resolve()
    profile = json.loads(profile_path.read_text(encoding="utf-8"))
    allowed_profiles = {
        "grasu_regraph_normalized_pagerank_spine23",
        "grasu_regraph_candidate10_normalized_pagerank_v2",
        "grasu_regraph_candidate10_k1_multipart_pagerank_v4",
        "grasu_regraph_candidate10_k2_multipart_pagerank_v4",
        "grasu_regraph_candidate10_k4_multipart_pagerank_v4",
    }
    if profile.get("profile_id") not in allowed_profiles:
        raise ValueError("runner requires the pinned normalized PageRank profile")
    params = profile["parameters"]
    damping = (
        float(params["pagerank_damping"])
        if args.damping is None
        else args.damping
    )
    if not 0.0 < damping < 1.0:
        raise ValueError("damping must be between zero and one")
    memory = profile["memory"]
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
    partition_vertices = 16 if args.smoke else 65_536
    env = os.environ.copy()
    env.update(
        {
            "GRASU_SST_MODE": "grasu_regraph_pagerank",
            "GRASU_SST_CHANNELS": str(memory["channels"]),
            "GRASU_SST_ACTIVE_CHANNELS": ",".join(
                str(channel) for channel in binding.instantiated_channels
            ),
            "GRASU_SST_CHANNEL_BYTES": str(memory["channel_capacity_bytes"]),
            "GRASU_SST_WORKLOAD": str(workload_path),
            "GRASU_SST_UPDATE_WORKLOAD": "",
            "GRASU_SST_OUTPUT": str(result_path),
            "GRASU_SST_DRAM_OUTPUT": str(dram_dir),
            "GRASU_SST_CORE_MHZ": str(kernel_clock["achieved_mhz"]),
            "GRASU_SST_MAX_CYCLES": str(args.max_cycles),
            "GRASU_SST_PAGERANK_ITERATIONS": str(args.iterations),
            "GRASU_SST_PAGERANK_DAMPING": str(damping),
            "GRASU_SST_CACHE_SEGMENTS_PER_HALF": str(
                params["grasu_cache_segments_per_cu"]
            ),
            "GRASU_SST_PARTITION_VERTICES": str(partition_vertices),
            "GRASU_SST_COMPUTE_PIPELINES": str(
                params.get("regraph_compute_pipelines", 1)
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
                memory["max_outstanding_per_port"]
            ),
            "GRASU_SST_APPLY_PIPELINE_LATENCY": "100",
            "GRASU_SST_APPLY_PIPELINE_CAPACITY": "100",
            "GRASU_SST_HBM_WRAPPER_PIPELINE_LATENCY": str(
                params["regraph_hbm_wrapper_pipeline_latency"]
            ),
            "GRASU_SST_HBM_WRAPPER_PIPELINE_CAPACITY": str(
                params["regraph_hbm_wrapper_pipeline_capacity"]
            ),
        }
    )
    library_binding = forced_sst_library_binding(args.sst, args.lib_dir)
    command = [
        str(args.sst.resolve()),
        library_binding["command_option"],
        str(ROOT / "sst" / "grasu_regraph_vertical.py"),
    ]
    sst_start = time.monotonic()
    completed = subprocess.run(
        command,
        cwd=ROOT,
        env=env,
        check=False,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
    )
    sst_host_wall_seconds = time.monotonic() - sst_start
    (args.out_dir / "sst.log").write_text(completed.stdout, encoding="utf-8")
    if completed.returncode != 0:
        raise RuntimeError(
            f"SST GraSU/ReGraph PageRank failed with rc={completed.returncode}; "
            f"see {args.out_dir / 'sst.log'}"
        )

    result = json.loads(result_path.read_text(encoding="utf-8"))
    dram = load_dram_stats(dram_dir)
    expected_claim = (
        "component_validation_simulation" if args.smoke else "normalized_simulation"
    )
    expected_rows = partition_vertices // 2 * args.iterations
    expected_bursts = partition_vertices // 16 * args.iterations
    expected_active_edges = result.get("initial_edges", -1) * args.iterations
    vertices = result.get("vertices", -1)
    expected_row_reads = vertices * args.iterations
    expected_prepare_bursts = (vertices + 15) // 16
    expected_degree_reads = expected_bursts + expected_prepare_bursts
    expected_source_writes = 2 * (expected_bursts + expected_prepare_bursts)
    expected_source_requests = expected_pagerank_source_cache_requests(
        vertices,
        params["regraph_source_buffer_vertices"],
        args.iterations,
    )
    expected_source_lines = (
        expected_source_requests * params["regraph_source_buffer_vertices"] // 16
    )
    expected_compute_read_bytes = sum(
        result.get(field, -1)
        for field in (
            "source_prepare_state_read_bytes",
            "row_read_bytes",
            "source_state_read_bytes",
            "degree_read_bytes",
            "pma_read_bytes",
            "apply_read_bytes",
        )
    )
    expected_compute_write_bytes = (
        expected_bursts + expected_source_writes
    ) * 64
    expected_compute_backend_requests = (
        expected_prepare_bursts
        + expected_prepare_bursts
        + expected_row_reads
        + expected_source_lines
        + result.get("compute_pma_segment_reads", -1)
        + 16 * expected_bursts
        + expected_bursts
        + expected_bursts
        + expected_source_writes
    )
    expected_backend_writes = expected_bursts + expected_source_writes
    ranks = result.get("ranks", [])
    rank_values = [float(rank) for rank in ranks] if isinstance(ranks, list) else []
    accurate_rank_sum = math.fsum(rank_values)
    accurate_rank_sum_error = abs(accurate_rank_sum - 1.0)
    rank_sum_tolerance = full_pagerank_rank_sum_tolerance(
        vertices,
        result.get("mathematical_max_abs_error", 1.0),
    )
    reported_rank_sum = float(result.get("rank_sum", math.nan))
    reported_rank_sum_error = abs(reported_rank_sum - 1.0)
    reported_rank_sum_tolerance = float32_sequential_rank_sum_tolerance(
        vertices, rank_sum_tolerance
    )
    if (
        not result.get("success")
        or result.get("mode") != "grasu_regraph_pagerank"
        or result.get("claim_class") != expected_claim
        or result.get("correctness_mismatches") != 0
        or result.get("architecture_correctness_mismatches") != 0
        or result.get("mathematical_correctness_mismatches") != 0
        or result.get("architecture_oracle") != "iterative_float32"
        or result.get("mathematical_oracle") != "iterative_float64"
        or result.get("max_abs_error", 1.0) > 1.0e-5
        or result.get("mathematical_max_abs_error", 1.0) > 1.0e-5
        or len(rank_values) != vertices
        or not all(math.isfinite(rank) for rank in rank_values)
        or accurate_rank_sum_error > rank_sum_tolerance
        or not math.isfinite(reported_rank_sum)
        or reported_rank_sum_error > reported_rank_sum_tolerance
        or result.get("iterations") != args.iterations
        or abs(result.get("pagerank_damping", -1.0) - damping) > 1.0e-7
        or abs(result.get("core_mhz", -1.0) - kernel_clock["achieved_mhz"])
        > 1.0e-9
        or result.get("updates") != 0
        or result.get("degree_update_timing_included") is not False
        or result.get("degree_updates_required") != 0
        or result.get("partition_vertices") != partition_vertices
        or result.get("degree_channel") != params["regraph_degree_channel"]
        or result.get("pagerank_source_map_latency")
        != params["regraph_pagerank_source_map_latency"]
        or result.get("degree_reads") != expected_degree_reads
        or result.get("degree_read_bytes") != 64 * expected_degree_reads
        or result.get("source_prepare_state_reads") != expected_prepare_bursts
        or result.get("source_prepare_degree_reads") != expected_prepare_bursts
        or result.get("source_prepare_writes") != 2 * expected_prepare_bursts
        or result.get("source_prepare_state_read_bytes")
        != 64 * expected_prepare_bursts
        or result.get("source_prepare_cycles", 0) <= 128
        or result.get("source_map_cycles") != 0
        or result.get("compute_live_edges") != expected_active_edges
        or result.get("compute_active_edges") != expected_active_edges
        or result.get("compute_row_reads") != expected_row_reads
        or result.get("gather_bank_updates") != expected_active_edges
        or result.get("gather_rows_emitted") != expected_rows
        or result.get("merger_rows_consumed") != expected_rows
        or result.get("merger_bursts_emitted") != expected_bursts
        or result.get("apply_input_bursts") != expected_bursts
        or result.get("hbm_wrapper_input_bursts") != expected_bursts
        or result.get("apply_state_reads") != expected_bursts
        or result.get("apply_state_writes") != expected_bursts
        or result.get("compute_source_state_writes") != expected_source_writes
        or result.get("source_cache_requests") != expected_source_requests
        or result.get("source_cache_lines") != expected_source_lines
        or result.get("source_cache_lane_writes")
        != expected_source_lines * params["regraph_map_reduce_lanes"]
        or not 0 < result.get("gather_merger_fifo_max_occupancy", 0)
        <= params["regraph_gather_merger_fifo_depth"]
        or not 0 < result.get("merger_apply_fifo_max_occupancy", 0)
        <= params["regraph_merger_apply_fifo_depth"]
        or not 0 < result.get("apply_wrapper_fifo_max_occupancy", 0)
        <= params["regraph_apply_wrapper_fifo_depth"]
        or result.get("compute_read_bytes") != expected_compute_read_bytes
        or result.get("compute_write_bytes") != expected_compute_write_bytes
        or result.get("compute_axi_beats_issued")
        != expected_compute_backend_requests
        or result.get("compute_axi_beats_completed")
        != expected_compute_backend_requests
        or result.get("compute_backend_requests")
        != expected_compute_backend_requests
        or result.get("expected_backend_requests")
        != expected_compute_backend_requests
        or result.get("backend_requests") != expected_compute_backend_requests
        or result.get("memory_locality_ledger_match") is not True
        or dram["channels"] != len(binding.instantiated_channels)
        or dram["writes"] != expected_backend_writes
        or dram["reads"] != expected_compute_backend_requests - expected_backend_writes
    ):
        raise RuntimeError(f"SST GraSU/ReGraph PageRank validation failed: {result}")

    manifest = {
        "schema_version": 1,
        "profile": str(profile_path),
        "profile_sha256": sha256(profile_path),
        "workload": str(workload_path),
        "workload_sha256": sha256(workload_path),
        "iterations": args.iterations,
        "damping": damping,
        "smoke": args.smoke,
        "sst_memory_binding": binding.as_manifest(),
        "sst_library_binding": library_binding,
        "sst_host_wall_seconds": sst_host_wall_seconds,
        "validation": {
            "accurate_rank_sum": accurate_rank_sum,
            "accurate_rank_sum_error": accurate_rank_sum_error,
            "accurate_rank_sum_tolerance": rank_sum_tolerance,
            "reported_float32_rank_sum": reported_rank_sum,
            "reported_float32_rank_sum_error": reported_rank_sum_error,
            "reported_float32_rank_sum_tolerance": reported_rank_sum_tolerance,
            "rank_sum_tolerance_basis": (
                "accurate_fsum_uses_1e-5_plus_vertices_times_per_vertex_error;_"
                "reported_sum_adds_standard_float32_sequential_gamma_bound"
            ),
        },
        "command": command,
        "result": result,
        "dram": dram,
        "status": "PASS",
    }
    (args.out_dir / "manifest.json").write_text(
        json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    print(
        "PASS grasu_regraph_pagerank_sst: "
        f"claim={result['claim_class']} cycles={result['cycles']} "
        f"iterations={result['iterations']} max_error={result['max_abs_error']} "
        f"backend_requests={result['backend_requests']}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
