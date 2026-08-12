#!/usr/bin/env python3
"""Run frozen G+R update-only SST evidence without materializing the graph in Python."""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import time
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.run_sst_grasu_regraph import load_dram_stats, sha256  # noqa: E402
from spine_cycle_sim.experiments.grasu_addressing import (  # noqa: E402
    grasu_hbm_address_environment,
    selected_source_state_stride_bytes,
)
from spine_cycle_sim.sst_binding import grasu_normalized_memory_binding  # noqa: E402
from spine_cycle_sim.sst_library import forced_sst_library_binding  # noqa: E402


DEFAULT_CONTRACT = (
    ROOT / "configs/contracts/current_fpga_grasu_persistent_update_v19.json"
)
DEFAULT_SST = Path("/data/feiyang/sst/bin/sst")
ALGORITHMS = (
    "weighted_sssp",
    "connected_components",
    "thresholded_residual_pagerank",
)
MODES = {
    "weighted_sssp": "grasu_regraph_hls_weighted_sssp",
    "connected_components": "grasu_regraph_connected_components",
    "thresholded_residual_pagerank": (
        "grasu_regraph_hls_weighted_residual_pagerank"
    ),
}


def read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def slice_metadata(path: Path) -> tuple[str, int, int]:
    """Read slice metadata and count records with constant host memory."""

    case_id = path.stem
    vertices: int | None = None
    records = 0
    with path.open(encoding="ascii") as source:
        for line_number, raw_line in enumerate(source, start=1):
            line = raw_line.strip()
            if not line:
                continue
            if line.startswith("#"):
                metadata = line[1:].strip()
                if metadata.startswith("case="):
                    case_id = metadata.split("=", 1)[1].strip()
                elif metadata.startswith("vertices="):
                    vertices = int(metadata.split("=", 1)[1])
                continue
            fields = line.split()
            if len(fields) != 4:
                raise ValueError(f"{path}:{line_number}: expected four edge fields")
            src, dst, weight, diff = map(int, fields)
            if vertices is None:
                raise ValueError(f"{path}:{line_number}: records precede vertices")
            if not (0 <= src < vertices and 0 <= dst < vertices):
                raise ValueError(f"{path}:{line_number}: vertex is out of range")
            if not (1 <= weight <= 4095) or abs(diff) != 1:
                raise ValueError(f"{path}:{line_number}: record exceeds weighted ABI")
            records += 1
    if vertices is None or vertices <= 0:
        raise ValueError(f"{path}: missing or invalid vertices metadata")
    return case_id, vertices, records


def profile_environment(
    profile: dict[str, Any],
    *,
    algorithm: str,
    workload: Path,
    update_workload: Path,
    result_path: Path,
    dram_dir: Path,
    progress_path: Path,
    source_vertex: int,
    vertices: int,
    max_cycles: int,
) -> tuple[dict[str, str], dict[str, object], int]:
    params = profile["parameters"]
    memory = profile["memory"]
    partition_vertices = int(params["regraph_partition_vertices"])
    destination_partitions = (vertices + partition_vertices - 1) // partition_vertices
    source_stride = selected_source_state_stride_bytes(
        params, destination_partitions
    )
    binding = grasu_normalized_memory_binding(profile)
    kernel_clock = next(
        clock for clock in profile["clocks"] if clock["name"] == "kernel"
    )
    environment = {
        "GRASU_SST_MODE": MODES[algorithm],
        "GRASU_SST_CHANNELS": str(memory["channels"]),
        "GRASU_SST_ACTIVE_CHANNELS": ",".join(
            str(channel) for channel in binding.instantiated_channels
        ),
        "GRASU_SST_CHANNEL_BYTES": str(memory["channel_capacity_bytes"]),
        "GRASU_SST_WORKLOAD": str(workload),
        "GRASU_SST_UPDATE_WORKLOAD": str(update_workload),
        "GRASU_SST_SOURCE": str(source_vertex),
        "GRASU_SST_OUTPUT": str(result_path),
        "GRASU_SST_DRAM_OUTPUT": str(dram_dir),
        "GRASU_SST_CORE_MHZ": str(kernel_clock["achieved_mhz"]),
        "GRASU_SST_MAX_CYCLES": str(max_cycles),
        "GRASU_SST_MAX_ROUNDS": str(
            params.get("pagerank_residual_max_iterations", 4096)
        ),
        "GRASU_SST_UPDATE_ONLY": "1",
        "GRASU_SST_WEIGHTED_HOST_PREPARATION": "1",
        "GRASU_SST_CC_HARDWARE_FULL_RECOMPUTE": "0",
        "GRASU_SST_NATIVE_SUPERSTEPS": "1",
        "GRASU_SST_HARDWARE_WARM_SSSP": "0",
        "GRASU_SST_CACHE_SEGMENTS_PER_HALF": str(
            params["grasu_cache_segments_per_cu"]
        ),
        "GRASU_SST_PARTITION_VERTICES": str(partition_vertices),
        "GRASU_SST_COMPUTE_PIPELINES": str(
            params.get("regraph_compute_pipelines", 1)
        ),
        "GRASU_SST_SHARED_DOWNSTREAM": (
            "1" if params.get("regraph_downstream_sharing") == "shared" else "0"
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
        "GRASU_SST_SOURCE_STATE_BUFFER_STRIDE": str(source_stride),
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
        "GRASU_SST_SPLIT_PAGERANK_STATE": (
            "1" if params.get("regraph_split_pagerank_state", False) else "0"
        ),
        "GRASU_SST_RESIDUAL_STATE_CHANNEL": str(
            params.get("regraph_residual_state_channel", 26)
        ),
        "GRASU_SST_DEGREE_CHANNEL": str(params.get("regraph_degree_channel", 30)),
        "GRASU_SST_DEGREE_FIFO_DEPTH": str(
            params.get("grasu_degree_fifo_depth", 16)
        ),
        "GRASU_SST_DEGREE_REORDER_ENTRIES": str(
            params.get("grasu_degree_reorder_entries", 4096)
        ),
        "GRASU_SST_PAGERANK_SOURCE_MAP_LATENCY": str(
            params.get("regraph_pagerank_source_map_latency", 1)
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
        "GRASU_SST_PAGERANK_DAMPING": str(params.get("pagerank_damping", 0.85)),
        "GRASU_SST_PAGERANK_EPSILON": str(
            params.get("pagerank_epsilon", 0.000001)
        ),
        "GRASU_SST_RESIDUAL_CONTRACT": str(
            params.get("pagerank_residual_contract", "generic_dangling_l1_cold")
        ),
        "GRASU_SST_RESIDUAL_MAX_ITERATIONS": str(
            params.get("pagerank_residual_max_iterations", 256)
        ),
        "SPINE_CAMPAIGN_PROGRESS_PATH": str(progress_path),
        "SPINE_CAMPAIGN_PROGRESS_INTERVAL_CYCLES": "1000000",
    }
    environment.update(grasu_hbm_address_environment(params))
    environment["GRASU_SST_RESIDUAL_STATE_BASE"] = str(
        params.get("grasu_residual_state_base_bytes", 0x42000000)
    )
    return environment, binding.as_manifest(), source_stride


def validate_result(
    result: dict[str, Any], *, algorithm: str, update_records: int
) -> dict[str, bool]:
    observability = result.get("update_observability")
    checks = {
        "success": result.get("success") is True,
        "mode": result.get("mode") == MODES[algorithm],
        "measurement_window": result.get("measurement_window")
        == "pure_update_only",
        "pipeline_order": result.get("pipeline_order")
        == "update_only_no_regraph_compute",
        "conversion_absent": result.get("conversion_cost_included") is False,
        "logical_updates": int(result.get("logical_updates", -1)) == update_records,
        "physical_updates": int(result.get("physical_updates", -1))
        == update_records,
        "positive_update_cycles": int(result.get("update_cycles", 0)) > 0,
        "zero_compute_cycles": int(result.get("compute_cycles", -1)) == 0,
        "update_state": result.get("update_state_match") is True,
        "memory_ledger": result.get("memory_locality_ledger_match") is True,
        "correctness": int(result.get("correctness_mismatches", -1)) == 0,
        "architecture_correctness": int(
            result.get("architecture_correctness_mismatches", -1)
        )
        == 0,
        "mathematical_correctness": int(
            result.get("mathematical_correctness_mismatches", -1)
        )
        == 0,
        "observability": isinstance(observability, dict)
        and int(observability.get("updates", -1)) == update_records
        and int(observability.get("destination_partitions_touched", 0)) > 0,
    }
    if algorithm == "thresholded_residual_pagerank":
        checks["degree_ledger"] = (
            isinstance(observability, dict)
            and int(observability.get("degree_reads", -1)) == update_records
            and int(observability.get("degree_writes", -1)) == update_records
        )
    return checks


def git_revision() -> str:
    return subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=ROOT,
        check=True,
        text=True,
        stdout=subprocess.PIPE,
    ).stdout.strip()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--algorithm", choices=ALGORITHMS, required=True)
    parser.add_argument("--workload", type=Path, required=True)
    parser.add_argument("--update-workload", type=Path, required=True)
    parser.add_argument("--out-dir", type=Path, required=True)
    parser.add_argument("--contract", type=Path, default=DEFAULT_CONTRACT)
    parser.add_argument("--source", type=int, default=0)
    parser.add_argument("--sst", type=Path, default=DEFAULT_SST)
    parser.add_argument("--lib-dir", type=Path)
    parser.add_argument("--max-cycles", type=int, default=30_000_000)
    args = parser.parse_args()
    if args.max_cycles <= 0:
        raise ValueError("max cycles must be positive")

    contract_path = args.contract.resolve()
    contract = read_json(contract_path)
    profile_entry = contract["profiles"][args.algorithm]
    profile_path = (ROOT / profile_entry["path"]).resolve()
    plugin_dir = (
        args.lib_dir.resolve()
        if args.lib_dir is not None
        else (ROOT / contract["plugin"]["path"]).resolve().parent
    )
    workload = args.workload.resolve()
    update_workload = args.update_workload.resolve()
    profile = read_json(profile_path)
    if sha256(profile_path) != profile_entry["sha256"]:
        raise ValueError("profile differs from the frozen contract")
    if profile.get("profile_id") != profile_entry["profile_id"]:
        raise ValueError("profile ID differs from the frozen contract")
    plugin = plugin_dir / "libspine_cycle.so"
    if sha256(plugin) != contract["plugin"]["sha256"]:
        raise ValueError("SST plugin differs from the frozen contract")

    _, vertices, initial_records = slice_metadata(workload)
    _, update_vertices, update_records = slice_metadata(update_workload)
    if update_vertices != vertices or update_records <= 0:
        raise ValueError("update slice must be nonempty and match the initial graph")
    if not 0 <= args.source < vertices:
        raise ValueError("source vertex is out of range")

    args.out_dir.mkdir(parents=True, exist_ok=True)
    result_path = (args.out_dir / "result.json").resolve()
    log_path = (args.out_dir / "sst.log").resolve()
    dram_dir = (args.out_dir / "dram").resolve()
    progress_path = (args.out_dir / "progress.json").resolve()
    result_path.unlink(missing_ok=True)
    log_path.unlink(missing_ok=True)
    progress_path.unlink(missing_ok=True)
    shutil.rmtree(dram_dir, ignore_errors=True)

    run_environment, memory_binding, source_stride = profile_environment(
        profile,
        algorithm=args.algorithm,
        workload=workload,
        update_workload=update_workload,
        result_path=result_path,
        dram_dir=dram_dir,
        progress_path=progress_path,
        source_vertex=args.source,
        vertices=vertices,
        max_cycles=args.max_cycles,
    )
    sst_library = forced_sst_library_binding(args.sst, plugin_dir)
    sst_config = (ROOT / "sst/grasu_regraph_vertical.py").resolve()
    command = [
        str(args.sst.resolve()),
        sst_library["command_option"],
        str(sst_config),
    ]
    environment = os.environ.copy()
    environment.update(run_environment)
    started = time.monotonic()
    with log_path.open("w", encoding="utf-8") as log:
        completed = subprocess.run(
            command,
            cwd=ROOT,
            env=environment,
            check=False,
            text=True,
            stdout=log,
            stderr=subprocess.STDOUT,
        )
    wall_seconds = time.monotonic() - started
    if completed.returncode != 0:
        raise RuntimeError(f"streaming SST failed; see {log_path}")

    result = read_json(result_path)
    checks = validate_result(
        result, algorithm=args.algorithm, update_records=update_records
    )
    dram = load_dram_stats(dram_dir)
    checks["dram_request_ledger"] = (
        int(dram["channels"]) == len(memory_binding["instantiated_channels"])
        and int(dram["reads"]) + int(dram["writes"])
        == int(result["backend_requests"])
    )
    failed = [name for name, passed in checks.items() if not passed]
    manifest = {
        "schema_version": 1,
        "status": "PASS" if not failed else "FAIL",
        "admitted": not failed,
        "claim_class": "frozen_plugin_streaming_transfer_validation",
        "algorithm": args.algorithm,
        "source_revision": contract["plugin"]["source_revision"],
        "runner_source_revision": git_revision(),
        "contract": str(contract_path),
        "contract_sha256": sha256(contract_path),
        "profile": str(profile_path),
        "profile_id": profile_entry["profile_id"],
        "profile_sha256": sha256(profile_path),
        "sst_config": str(sst_config),
        "sst_config_sha256": sha256(sst_config),
        "sst_plugin": str(plugin),
        "sst_plugin_sha256": sha256(plugin),
        "sst_library_binding": sst_library,
        "workload": str(workload),
        "workload_sha256": sha256(workload),
        "update_workload": str(update_workload),
        "update_workload_sha256": sha256(update_workload),
        "vertices": vertices,
        "initial_records": initial_records,
        "update_records": update_records,
        "source_external": args.source,
        "measurement_window": "pure_update_only",
        "graph_compute_executed": False,
        "host_preflight_storage": "streaming_constant_memory_no_python_graph_oracle",
        "correctness_authority": (
            "frozen_cxx_plugin_architecture_and_independent_mathematical_references"
        ),
        "runtime_source_state_stride_bytes": source_stride,
        "sst_memory_binding": memory_binding,
        "environment": run_environment,
        "command": command,
        "sst_host_wall_seconds": wall_seconds,
        "checks": checks,
        "failed_checks": failed,
        "result": result,
        "dram": dram,
    }
    (args.out_dir / "run_manifest.json").write_text(
        json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="ascii"
    )
    if failed:
        raise RuntimeError(f"streaming transfer validation failed: {failed}")
    print(
        "PASS streaming_grasu_update_only_v19: "
        f"algorithm={args.algorithm} vertices={vertices} "
        f"initial={initial_records} updates={update_records} "
        f"cycles={result['update_cycles']} wall_s={wall_seconds:.3f}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
