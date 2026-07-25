#!/usr/bin/env python3
"""Run the profile-pinned GraSU + PMA-native ReGraph SST vertical slice."""

from __future__ import annotations

import argparse
import hashlib
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

from spine_cycle_sim.sst_binding import grasu_normalized_memory_binding  # noqa: E402


DEFAULT_SST = Path("/data/feiyang/sst/bin/sst")
DEFAULT_PROFILE = (
    ROOT
    / "configs"
    / "architectures"
    / "grasu_regraph_normalized_weighted_spine23.json"
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
    parser.add_argument(
        "--workload",
        type=Path,
        default=ROOT / "tests" / "data" / "grasu_regraph_unit_initial.slice",
    )
    parser.add_argument(
        "--update-workload",
        type=Path,
        default=ROOT / "tests" / "data" / "grasu_regraph_unit_update.slice",
    )
    parser.add_argument("--source", type=int, default=0)
    parser.add_argument("--out-dir", type=Path, required=True)
    parser.add_argument("--sst", type=Path, default=DEFAULT_SST)
    parser.add_argument("--lib-dir", type=Path, default=ROOT / "build" / "sst")
    parser.add_argument("--max-cycles", type=int, default=20_000_000)
    parser.add_argument("--max-rounds", type=int, default=256)
    parser.add_argument(
        "--smoke",
        action="store_true",
        help="Use a 16-word partition and label the result component validation.",
    )
    parser.add_argument("--no-build", action="store_true")
    parser.add_argument(
        "--instantiate-all-hbm-channels",
        action="store_true",
        help="instantiate idle SST HBM controllers for equivalence or energy runs",
    )
    args = parser.parse_args()

    profile_path = args.profile.resolve()
    profile = json.loads(profile_path.read_text(encoding="utf-8"))
    if profile.get("profile_id") != "grasu_regraph_normalized_weighted_spine23":
        raise ValueError(
            "runner requires the pinned weighted normalized GraSU/ReGraph profile"
        )
    params = profile["parameters"]
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
            "GRASU_SST_MAX_ROUNDS": str(args.max_rounds),
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
            f"SST GraSU/ReGraph failed with rc={completed.returncode}; "
            f"see {args.out_dir / 'sst.log'}"
        )

    result = json.loads(result_path.read_text(encoding="utf-8"))
    dram = load_dram_stats(dram_dir)
    expected_claim = (
        "component_validation_simulation" if args.smoke else "normalized_simulation"
    )
    supersteps = result.get("supersteps", -1)
    expected_rows = partition_vertices // 2 * supersteps
    expected_bursts = partition_vertices // 16 * supersteps
    expected_source_requests = result.get("source_cache_requests", -1)
    expected_source_lines = (
        expected_source_requests * params["regraph_source_buffer_vertices"] // 16
    )
    if (
        not result.get("success")
        or result.get("correctness_mismatches") != 0
        or result.get("architecture_correctness_mismatches") != 0
        or result.get("mathematical_correctness_mismatches") != 0
        or result.get("architecture_oracle")
        != "synchronous_frontier_uint32"
        or result.get("mathematical_oracle") != "uint64_dijkstra"
        or result.get("claim_class") != expected_claim
        or abs(result.get("core_mhz", -1.0) - kernel_clock["achieved_mhz"])
        > 1.0e-9
        or result.get("partition_vertices") != partition_vertices
        or result.get("source_state_channel")
        != params["regraph_source_state_channel"]
        or result.get("source_state_mirror_channel")
        != params["regraph_source_state_mirror_channel"]
        or result.get("apply_state_channel") != params["regraph_apply_state_channel"]
        or result.get("pma_edge_abi") != params["grasu_pma_edge_abi"]
        or sum(
            result.get(field, -1)
            for field in (
                "update_inserts",
                "update_deletes",
                "update_weight_decreases",
                "update_weight_increases",
            )
        )
        != result.get("updates", -2)
        or result.get("compute_source_state_writes")
        != 2 * result.get("apply_state_writes", -1)
        or expected_source_requests < 2 * supersteps
        or result.get("compute_source_state_reads") != expected_source_requests
        or result.get("source_cache_lines") != expected_source_lines
        or result.get("source_cache_lane_writes")
        != expected_source_lines * params["regraph_map_reduce_lanes"]
        or result.get("source_cache_request_markers") != supersteps
        or result.get("source_cache_response_markers") != supersteps
        or not 0 < result.get("source_cache_request_fifo_max_occupancy", 0)
        <= params["regraph_source_cache_request_fifo_depth"]
        or not 0 < result.get("source_cache_response_fifo_max_occupancy", 0)
        <= params["regraph_source_cache_response_fifo_depth"]
        or result.get("gather_bank_conflict_cycles") != 0
        or result.get("gather_bank_updates")
        != result.get("compute_active_edges", -1)
        or result.get("gather_bypass_hits", 0)
        + result.get("gather_bypass_misses", 0)
        != result.get("gather_bank_updates", -1)
        or result.get("gather_pipeline_drain_cycles")
        != supersteps * (params["regraph_gather_pipeline_latency"] - 1)
        or result.get("compute_write_bytes")
        != 3 * result.get("apply_state_writes", -1) * 64
        or result.get("gather_rows_emitted") != expected_rows
        or result.get("merger_rows_consumed") != expected_rows
        or result.get("merger_bursts_emitted") != expected_bursts
        or result.get("apply_input_bursts") != expected_bursts
        or result.get("hbm_wrapper_input_bursts") != expected_bursts
        or not 0 < result.get("gather_merger_fifo_max_occupancy", 0)
        <= params["regraph_gather_merger_fifo_depth"]
        or not 0 < result.get("merger_apply_fifo_max_occupancy", 0)
        <= params["regraph_merger_apply_fifo_depth"]
        or not 0 < result.get("apply_wrapper_fifo_max_occupancy", 0)
        <= params["regraph_apply_wrapper_fifo_depth"]
        or dram["channels"] != len(binding.instantiated_channels)
        or dram["reads"] + dram["writes"] != result.get("backend_requests")
    ):
        raise RuntimeError(f"SST GraSU/ReGraph validation failed: {result}")

    manifest = {
        "schema_version": 1,
        "profile": str(profile_path),
        "profile_sha256": sha256(profile_path),
        "workload": str(args.workload.resolve()),
        "workload_sha256": sha256(args.workload.resolve()),
        "update_workload": str(args.update_workload.resolve()),
        "update_workload_sha256": sha256(args.update_workload.resolve()),
        "smoke": args.smoke,
        "sst_memory_binding": binding.as_manifest(),
        "sst_host_wall_seconds": sst_host_wall_seconds,
        "command": command,
        "result": result,
        "dram": dram,
        "status": "PASS",
    }
    (args.out_dir / "manifest.json").write_text(
        json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    print(
        "PASS grasu_regraph_sst: "
        f"claim={result['claim_class']} cycles={result['cycles']} "
        f"update={result['update_cycles']} compute={result['compute_cycles']} "
        f"backend_requests={result['backend_requests']}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
