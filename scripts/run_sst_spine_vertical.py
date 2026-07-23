#!/usr/bin/env python3
"""Run and validate the real Spine vertical slice on SST-HBM."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import subprocess
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_SST = Path("/data/feiyang/sst/bin/sst")
DEFAULT_WORKLOAD = ROOT / "tests" / "data" / "amazon_top1_exact.slice"
DEFAULT_CARRY_WORKLOAD = ROOT / "tests" / "data" / "carry_hot_batch.slice"
DEFAULT_CARRY_PRELOAD = ROOT / "tests" / "data" / "carry_hot_preload.slice"
DEFAULT_FULL_WORKLOAD = (
    ROOT / "tests" / "data" / "amazon_densewin8192_active7893_exact.slice"
)
DEFAULT_SSSP_WORKLOAD = ROOT / "tests" / "data" / "weighted_chain_shortcut.slice"
PROFILE_PATH = ROOT / "configs" / "architectures" / "spine_shared_engine_9c08763.json"


def collect_dram_stats(out_dir: Path) -> dict[str, int | float]:
    totals: dict[str, int | float] = {
        "dram_channels": 0,
        "dram_reads": 0,
        "dram_writes": 0,
        "dram_activates": 0,
        "dram_precharges": 0,
        "dram_read_row_hits": 0,
        "dram_write_row_hits": 0,
        "dram_total_energy_pj": 0.0,
    }
    paths = sorted((out_dir / "dram").glob("channel*/dramsim3.json"))
    if not paths:
        raise ValueError(f"no DRAMSim3 JSON found under {out_dir / 'dram'}")
    for path in paths:
        payload = json.loads(path.read_text(encoding="utf-8"))
        if len(payload) != 1:
            raise ValueError(f"expected one DRAM record in {path}")
        row = next(iter(payload.values()))
        totals["dram_channels"] += 1
        totals["dram_reads"] += int(row["num_reads_done"])
        totals["dram_writes"] += int(row["num_writes_done"])
        totals["dram_activates"] += int(row["num_act_cmds"])
        totals["dram_precharges"] += int(row["num_pre_cmds"])
        totals["dram_read_row_hits"] += int(row["num_read_row_hits"])
        totals["dram_write_row_hits"] += int(row["num_write_row_hits"])
        totals["dram_total_energy_pj"] += float(row["total_energy"])
    return totals


def validate_result(
    result: dict[str, Any], dram: dict[str, int | float], *, channels: int
) -> list[str]:
    checks = {
        "success": result.get("success") is True,
        "mode": result.get("mode") == "spine_vertical",
        "correctness": result.get("correctness_mismatches") == 0,
        "frontier_correctness": result.get("frontier_mismatches") == 0,
        "frontier": result.get("next_active") == 10,
        "maintenance_passes": result.get("maintenance_scan_passes") == 19,
        "maintenance_visits": result.get("maintenance_edge_visits") == 190,
        "maintenance_bytes": result.get("maintenance_sorted_bytes") == 3_040,
        "reader_tiles": result.get("reader_tiles") == 5,
        "reader_edges": result.get("reader_edges") == 10,
        "reader_bytes": result.get("reader_graph_bytes") == 224,
        "reader_metadata": result.get("reader_metadata_bytes") == 2_952,
        "reader_levels": result.get("reader_occupied_levels") == 1,
        "compute_fast_tiles": result.get("compute_fast_tiles") == 5,
        "compute_no_full_tiles": result.get("compute_full_tiles") == 0,
        "compute_edges": result.get("compute_processed_edges") == 10,
        "axis_transfers": result.get("edge_axis_transfers") == 22,
        "axis_capacity": 0 <= result.get("edge_axis_max_occupancy", -1) <= 32,
        "dram_matches_backend": int(dram.get("dram_reads", 0))
        + int(dram.get("dram_writes", 0))
        == result.get("backend_requests"),
        "channel_count": dram.get("dram_channels") == channels,
    }
    return [name for name, passed in checks.items() if not passed]


def validate_carry_hot_result(
    result: dict[str, Any], dram: dict[str, int | float], *, channels: int
) -> list[str]:
    checks = {
        "success": result.get("success") is True,
        "mode": result.get("mode") == "spine_vertical",
        "correctness": result.get("correctness_mismatches") == 0,
        "frontier_correctness": result.get("frontier_mismatches") == 0,
        "frontier": result.get("next_active") == 3,
        "input_shape": result.get("input_edges") == 2
        and result.get("preload_edges") == 1,
        "maintenance_targets": result.get("maintenance_target_level") == 1
        and result.get("maintenance_hot_target_level") == 0,
        "maintenance_partitioning": result.get("maintenance_cold_input_edges")
        == 1
        and result.get("maintenance_hot_input_edges") == 1,
        "maintenance_passes": result.get("maintenance_scan_passes") == 35,
        "maintenance_visits": result.get("maintenance_edge_visits") == 70,
        "maintenance_bytes": result.get("maintenance_sorted_bytes") == 1_120,
        "carry_work": result.get("maintenance_carry_payload_reads") == 1
        and result.get("maintenance_carry_merge_inputs") == 2
        and result.get("maintenance_carry_outputs") == 2,
        "reader_tiles": result.get("reader_tiles") == 1,
        "reader_edges": result.get("reader_edges") == 3,
        "reader_bytes": result.get("reader_graph_bytes") == 176,
        "reader_metadata": result.get("reader_metadata_bytes") == 3_024,
        "reader_levels": result.get("reader_occupied_levels") == 2,
        "reader_partitioning": result.get("reader_cold_edges") == 2
        and result.get("reader_hot_edges") == 1,
        "compute_fast_tiles": result.get("compute_fast_tiles") == 1,
        "compute_no_full_tiles": result.get("compute_full_tiles") == 0,
        "compute_edges": result.get("compute_processed_edges") == 3,
        "axis_capacity": 0 <= result.get("edge_axis_max_occupancy", -1) <= 32,
        "dram_matches_backend": int(dram.get("dram_reads", 0))
        + int(dram.get("dram_writes", 0))
        == result.get("backend_requests"),
        "channel_count": dram.get("dram_channels") == channels,
    }
    return [name for name, passed in checks.items() if not passed]


def validate_full_compute_result(
    result: dict[str, Any], dram: dict[str, int | float], *, channels: int
) -> list[str]:
    checks = {
        "success": result.get("success") is True,
        "mode": result.get("mode") == "spine_compute",
        "correctness": result.get("correctness_mismatches") == 0,
        "frontier_correctness": result.get("frontier_mismatches") == 0,
        "frontier_size": result.get("next_active")
        == result.get("expected_frontier"),
        "real_slice_edges": result.get("input_edges") == 64_658,
        "tile_paths": result.get("compute_fast_tiles") == 11
        and result.get("compute_full_tiles") == 1,
        "processed_edges": result.get("compute_processed_edges") == 64_658,
        "vertex_read_payload": result.get("compute_vertex_payload_read_bytes")
        == result.get("compute_vertex_read_bytes"),
        "vertex_write_payload": result.get("compute_vertex_payload_write_bytes")
        == result.get("compute_vertex_write_bytes"),
        "tiny_gathers": result.get("compute_gathered_words") == 14_676,
        "full_sweep": result.get("compute_swept_words") == 2 * 65_536,
        "finite_buffer_replay": result.get("compute_full_buffer_replay_edges")
        == 4096,
        "threshold_crossing": result.get("compute_full_overflow_edges") == 1,
        "stream_tail": result.get("compute_full_stream_edges") == 45_885,
        "axis_transfers": result.get("edge_axis_transfers") == 64_683,
        "axis_capacity": result.get("edge_axis_max_occupancy") == 32,
        "axis_backpressure": result.get("edge_axis_push_stalls", 0) > 0,
        "dram_matches_backend": int(dram.get("dram_reads", 0))
        + int(dram.get("dram_writes", 0))
        == result.get("backend_requests"),
        "channel_count": dram.get("dram_channels") == channels,
    }
    return [name for name, passed in checks.items() if not passed]


def validate_multiround_sssp_result(
    result: dict[str, Any], dram: dict[str, int | float], *, channels: int
) -> list[str]:
    checks = {
        "success": result.get("success") is True,
        "mode": result.get("mode") == "spine_sssp",
        "converged": result.get("converged") is True,
        "correctness": result.get("correctness_mismatches") == 0,
        "frontier_correctness": result.get("frontier_mismatches") == 0,
        "input_shape": result.get("input_edges") == 8,
        "round_count": result.get("rounds") == 6,
        "final_values": result.get("final_values") == [0, 3, 2, 7, 8, 10],
        "frontier_inputs": result.get("frontier_in_sizes") == [1, 3, 2, 2, 2, 1],
        "frontier_outputs": result.get("frontier_out_sizes") == [3, 2, 2, 2, 1, 0],
        "round_edges": result.get("processed_edges_per_round") == [3, 3, 2, 2, 1, 0],
        "maintenance_once": result.get("maintenance_scan_passes") == 19
        and result.get("maintenance_edge_visits") == 152,
        "round_timing": len(result.get("round_cycles", [])) == 6
        and all(cycles > 0 for cycles in result.get("round_cycles", [])),
        "round_fifo": len(result.get("edge_axis_max_occupancy_per_round", []))
        == 6
        and all(
            0 <= occupancy <= 32
            for occupancy in result.get("edge_axis_max_occupancy_per_round", [])
        )
        and len(result.get("edge_axis_push_stalls_per_round", [])) == 6,
        "round_tile_paths": result.get("full_tiles_per_round") == [0] * 6
        and len(result.get("fast_tiles_per_round", [])) == 6,
        "round_metadata": len(result.get("reader_metadata_bytes_per_round", []))
        == 6
        and all(
            value > 0 for value in result.get("reader_metadata_bytes_per_round", [])
        ),
        "dram_matches_backend": int(dram.get("dram_reads", 0))
        + int(dram.get("dram_writes", 0))
        == result.get("backend_requests"),
        "channel_count": dram.get("dram_channels") == channels,
    }
    return [name for name, passed in checks.items() if not passed]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out-dir", type=Path, required=True)
    parser.add_argument("--sst", type=Path, default=DEFAULT_SST)
    parser.add_argument("--lib-dir", type=Path, default=ROOT / "build" / "sst")
    parser.add_argument("--workload", type=Path, default=DEFAULT_WORKLOAD)
    parser.add_argument(
        "--scenario",
        choices=("amazon_l0", "carry_hot", "amazon_full_compute", "weighted_sssp"),
        default="amazon_l0",
    )
    parser.add_argument("--preload", type=Path)
    parser.add_argument("--hot-vertices", default="")
    parser.add_argument("--source", type=int)
    parser.add_argument("--channels", type=int, default=32)
    parser.add_argument("--no-build", action="store_true")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    if args.source is None:
        args.source = 2 if args.scenario == "amazon_l0" else 0
    if args.scenario == "carry_hot":
        if args.workload == DEFAULT_WORKLOAD:
            args.workload = DEFAULT_CARRY_WORKLOAD
        if args.preload is None:
            args.preload = DEFAULT_CARRY_PRELOAD
        if not args.hot_vertices:
            args.hot_vertices = "17"
    elif (
        args.scenario == "amazon_full_compute"
        and args.workload == DEFAULT_WORKLOAD
    ):
        args.workload = DEFAULT_FULL_WORKLOAD
    elif args.scenario == "weighted_sssp" and args.workload == DEFAULT_WORKLOAD:
        args.workload = DEFAULT_SSSP_WORKLOAD
    if args.channels < 23 or args.source < 0 or not args.workload.is_file():
        raise SystemExit("channels must be >=23, source non-negative, workload present")
    if args.preload is not None and not args.preload.is_file():
        raise SystemExit(f"preload workload is missing: {args.preload}")
    if not args.no_build:
        subprocess.run(["make", "-C", "cpp/sst"], cwd=ROOT, check=True)
    library = args.lib_dir / "libspine_cycle.so"
    if not library.is_file():
        raise SystemExit(f"missing SST element library: {library}")
    args.out_dir.mkdir(parents=True, exist_ok=True)
    result_path = args.out_dir / "result.json"
    env = os.environ.copy()
    env.update(
        {
            "SPINE_SST_CHANNELS": str(args.channels),
            "SPINE_SST_MODE": {
                "amazon_full_compute": "spine_compute",
                "weighted_sssp": "spine_sssp",
            }.get(args.scenario, "spine_vertical"),
            "SPINE_SST_WORKLOAD": str(args.workload.resolve()),
            "SPINE_SST_SOURCE": str(args.source),
            "SPINE_SST_PRELOAD": ""
            if args.preload is None
            else str(args.preload.resolve()),
            "SPINE_SST_HOT_VERTICES": args.hot_vertices,
            "SPINE_SST_OUTPUT": str(result_path),
            "SPINE_SST_DRAM_OUTPUT": str(args.out_dir / "dram"),
            "SPINE_SST_MAX_CYCLES": "5000000"
            if args.scenario == "amazon_full_compute"
            else "1000000",
            "SPINE_SST_MAX_ROUNDS": "256",
        }
    )
    command = [
        str(args.sst),
        f"--add-lib-path={args.lib_dir}",
        str(ROOT / "sst" / "spine_vertical_slice.py"),
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
            f"SST Spine vertical slice failed with rc={completed.returncode}; "
            f"see {args.out_dir / 'sst.log'}"
        )
    result = json.loads(result_path.read_text(encoding="utf-8"))
    dram = collect_dram_stats(args.out_dir)
    validators = {
        "amazon_l0": validate_result,
        "carry_hot": validate_carry_hot_result,
        "amazon_full_compute": validate_full_compute_result,
        "weighted_sssp": validate_multiround_sssp_result,
    }
    validator = validators[args.scenario]
    problems = validator(result, dram, channels=args.channels)
    if problems:
        raise RuntimeError(f"SST Spine checks failed: {', '.join(problems)}")
    profile_bytes = PROFILE_PATH.read_bytes()
    profile = json.loads(profile_bytes)
    summary = {
        **result,
        **dram,
        "architecture_profile_id": profile["profile_id"],
        "architecture_profile_sha256": hashlib.sha256(profile_bytes).hexdigest(),
        "source_revision": profile["source"]["revision"],
        "architecture_profile_evidence_tier": profile["evidence_tier"],
        "simulation_evidence_tier": "structural_execution_driven",
        "status": "PASS",
    }
    (args.out_dir / "summary.json").write_text(
        json.dumps(summary, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    print(
        f"PASS spine_vertical: cycles={result['cycles']} "
        f"backend_requests={result['backend_requests']} "
        f"DRAM={int(dram['dram_reads']) + int(dram['dram_writes'])} "
        f"ACT={dram['dram_activates']} row_hits="
        f"{int(dram['dram_read_row_hits']) + int(dram['dram_write_row_hits'])}"
    )
    print(f"evidence: {args.out_dir}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
