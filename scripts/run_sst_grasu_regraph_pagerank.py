#!/usr/bin/env python3
"""Run profile-pinned GraSU + PMA-native ReGraph Full PageRank on SST-HBM."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import subprocess


ROOT = Path(__file__).resolve().parents[1]
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


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--profile", type=Path, default=DEFAULT_PROFILE)
    parser.add_argument("--workload", type=Path, default=DEFAULT_WORKLOAD)
    parser.add_argument("--iterations", type=int, default=3)
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
    args = parser.parse_args()
    if args.iterations <= 0 or args.max_cycles <= 0:
        raise ValueError("iterations and max-cycles must be positive")

    profile_path = args.profile.resolve()
    workload_path = args.workload.resolve()
    profile = json.loads(profile_path.read_text(encoding="utf-8"))
    if profile.get("profile_id") != "grasu_regraph_normalized_pagerank_spine23":
        raise ValueError("runner requires the pinned normalized PageRank profile")
    params = profile["parameters"]
    memory = profile["memory"]
    kernel_clock = next(
        clock for clock in profile["clocks"] if clock["name"] == "kernel"
    )
    if not args.no_build:
        subprocess.run(["make", "-C", "cpp/sst", "-j2"], cwd=ROOT, check=True)

    args.out_dir.mkdir(parents=True, exist_ok=True)
    result_path = (args.out_dir / "result.json").resolve()
    dram_dir = (args.out_dir / "dram").resolve()
    partition_vertices = 16 if args.smoke else 65_536
    env = os.environ.copy()
    env.update(
        {
            "GRASU_SST_MODE": "grasu_regraph_pagerank",
            "GRASU_SST_CHANNELS": str(memory["channels"]),
            "GRASU_SST_CHANNEL_BYTES": str(memory["channel_capacity_bytes"]),
            "GRASU_SST_WORKLOAD": str(workload_path),
            "GRASU_SST_UPDATE_WORKLOAD": "",
            "GRASU_SST_OUTPUT": str(result_path),
            "GRASU_SST_DRAM_OUTPUT": str(dram_dir),
            "GRASU_SST_CORE_MHZ": str(kernel_clock["achieved_mhz"]),
            "GRASU_SST_MAX_CYCLES": str(args.max_cycles),
            "GRASU_SST_PAGERANK_ITERATIONS": str(args.iterations),
            "GRASU_SST_PAGERANK_DAMPING": str(params["pagerank_damping"]),
            "GRASU_SST_CACHE_SEGMENTS_PER_HALF": str(
                params["grasu_cache_segments_per_cu"]
            ),
            "GRASU_SST_PARTITION_VERTICES": str(partition_vertices),
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
    command = [
        str(args.sst.resolve()),
        f"--add-lib-path={args.lib_dir.resolve()}",
        str(ROOT / "sst" / "grasu_regraph_vertical.py"),
    ]
    completed = subprocess.run(
        command,
        cwd=ROOT,
        env=env,
        check=False,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
    )
    (args.out_dir / "sst.log").write_text(completed.stdout, encoding="utf-8")
    if completed.returncode != 0:
        raise RuntimeError(
            f"SST GraSU/ReGraph PageRank failed with rc={completed.returncode}; "
            f"see {args.out_dir / 'sst.log'}"
        )

    result = json.loads(result_path.read_text(encoding="utf-8"))
    expected_claim = (
        "component_validation_simulation" if args.smoke else "normalized_simulation"
    )
    expected_degree_reads = result.get("vertices", -1) * args.iterations
    expected_rows = partition_vertices // 2 * args.iterations
    expected_bursts = partition_vertices // 16 * args.iterations
    expected_active_edges = result.get("initial_edges", -1) * args.iterations
    expected_source_requests = result.get("source_cache_requests", -1)
    expected_source_lines = (
        expected_source_requests * params["regraph_source_buffer_vertices"] // 16
    )
    if (
        not result.get("success")
        or result.get("mode") != "grasu_regraph_pagerank"
        or result.get("claim_class") != expected_claim
        or result.get("correctness_mismatches") != 0
        or result.get("architecture_correctness_mismatches") != 0
        or result.get("mathematical_correctness_mismatches") != 0
        or result.get("max_abs_error", 1.0) > 1.0e-5
        or result.get("mathematical_max_abs_error", 1.0) > 1.0e-5
        or abs(result.get("rank_sum", 0.0) - 1.0) > 1.0e-5
        or result.get("iterations") != args.iterations
        or result.get("pagerank_damping") != params["pagerank_damping"]
        or result.get("updates") != 0
        or result.get("degree_update_timing_included") is not False
        or result.get("degree_updates_required") != 0
        or result.get("partition_vertices") != partition_vertices
        or result.get("degree_channel") != params["regraph_degree_channel"]
        or result.get("pagerank_source_map_latency")
        != params["regraph_pagerank_source_map_latency"]
        or result.get("degree_reads") != expected_degree_reads
        or result.get("degree_read_bytes") != 4 * expected_degree_reads
        or result.get("source_map_cycles")
        != expected_degree_reads * params["regraph_pagerank_source_map_latency"]
        or result.get("compute_live_edges") != expected_active_edges
        or result.get("compute_active_edges") != expected_active_edges
        or result.get("gather_bank_updates") != expected_active_edges
        or result.get("gather_rows_emitted") != expected_rows
        or result.get("merger_rows_consumed") != expected_rows
        or result.get("merger_bursts_emitted") != expected_bursts
        or result.get("apply_input_bursts") != expected_bursts
        or result.get("hbm_wrapper_input_bursts") != expected_bursts
        or result.get("apply_state_reads") != expected_bursts
        or result.get("apply_state_writes") != expected_bursts
        or result.get("compute_source_state_writes") != 2 * expected_bursts
        or expected_source_requests < 2 * args.iterations
        or result.get("source_cache_lines") != expected_source_lines
        or result.get("source_cache_lane_writes")
        != expected_source_lines * params["regraph_map_reduce_lanes"]
        or not 0 < result.get("gather_merger_fifo_max_occupancy", 0)
        <= params["regraph_gather_merger_fifo_depth"]
        or not 0 < result.get("merger_apply_fifo_max_occupancy", 0)
        <= params["regraph_merger_apply_fifo_depth"]
        or not 0 < result.get("apply_wrapper_fifo_max_occupancy", 0)
        <= params["regraph_apply_wrapper_fifo_depth"]
        or result.get("compute_write_bytes") != 3 * expected_bursts * 64
    ):
        raise RuntimeError(f"SST GraSU/ReGraph PageRank validation failed: {result}")

    manifest = {
        "schema_version": 1,
        "profile": str(profile_path),
        "profile_sha256": sha256(profile_path),
        "workload": str(workload_path),
        "workload_sha256": sha256(workload_path),
        "iterations": args.iterations,
        "smoke": args.smoke,
        "command": command,
        "result": result,
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
