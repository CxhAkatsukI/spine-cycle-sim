#!/usr/bin/env python3
"""Run the existing-HLS GraSU -> compactor -> ReGraph native SST baseline."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from spine_cycle_sim.experiments.grasu_native_validation import (  # noqa: E402
    native_active_hbm_channels,
    require_native_algorithm_capability,
    validate_result,
)


DEFAULT_SST = Path("/data/feiyang/sst/bin/sst")
DEFAULT_PROFILE = (
    ROOT / "configs" / "architectures" / "grasu_regraph_native_a9aef06.json"
)
DEFAULT_CAPABILITY_CATALOG = (
    ROOT / "configs" / "contracts" / "grasu_regraph_capabilities_v1.json"
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
    parser.add_argument(
        "--capability-catalog",
        type=Path,
        default=DEFAULT_CAPABILITY_CATALOG,
    )
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
    parser.add_argument("--supersteps", type=int)
    parser.add_argument("--out-dir", type=Path, required=True)
    parser.add_argument("--sst", type=Path, default=DEFAULT_SST)
    parser.add_argument("--lib-dir", type=Path, default=ROOT / "build" / "sst")
    parser.add_argument("--max-cycles", type=int, default=20_000_000)
    parser.add_argument("--no-build", action="store_true")
    parser.add_argument(
        "--instantiate-all-hbm-channels",
        action="store_true",
        help="instantiate idle SST HBM controllers for equivalence testing",
    )
    args = parser.parse_args()

    profile_path = args.profile.resolve()
    profile = json.loads(profile_path.read_text(encoding="utf-8"))
    if profile.get("profile_id") != "grasu_regraph_native_a9aef06":
        raise ValueError("runner requires the pinned native GraSU/ReGraph profile")
    capability_catalog, algorithm_capability = require_native_algorithm_capability(
        profile_path, args.capability_catalog.resolve()
    )
    params = profile["parameters"]
    memory = profile["memory"]
    active_channels = native_active_hbm_channels(profile)
    instantiated_channels = (
        tuple(range(int(memory["channels"])))
        if args.instantiate_all_hbm_channels
        else active_channels
    )
    kernel_clock = next(
        clock for clock in profile["clocks"] if clock["name"] == "kernel"
    )
    supersteps = args.supersteps or params["native_validation_supersteps"]
    if supersteps <= 0:
        raise ValueError("supersteps must be positive")
    if not args.no_build:
        subprocess.run(["make", "-C", "cpp/sst", "-j2"], cwd=ROOT, check=True)

    for evidence in profile.get("evidence", []):
        path = Path(evidence["path"])
        if not path.is_file() or sha256(path) != evidence["sha256"]:
            raise RuntimeError(f"native profile evidence mismatch: {path}")

    args.out_dir.mkdir(parents=True, exist_ok=True)
    result_path = (args.out_dir / "result.json").resolve()
    dram_dir = (args.out_dir / "dram").resolve()
    env = os.environ.copy()
    env.update(
        {
            "GRASU_SST_MODE": "grasu_regraph_native_sssp",
            "GRASU_SST_CHANNELS": str(memory["channels"]),
            "GRASU_SST_ACTIVE_CHANNELS": ",".join(
                str(channel) for channel in instantiated_channels
            ),
            "GRASU_SST_CHANNEL_BYTES": str(memory["channel_capacity_bytes"]),
            "GRASU_SST_WORKLOAD": str(args.workload.resolve()),
            "GRASU_SST_UPDATE_WORKLOAD": str(args.update_workload.resolve()),
            "GRASU_SST_SOURCE": str(args.source),
            "GRASU_SST_OUTPUT": str(result_path),
            "GRASU_SST_DRAM_OUTPUT": str(dram_dir),
            "GRASU_SST_CORE_MHZ": str(kernel_clock["achieved_mhz"]),
            "GRASU_SST_MAX_CYCLES": str(args.max_cycles),
            "GRASU_SST_MAX_ROUNDS": str(max(256, supersteps)),
            "GRASU_SST_NATIVE_SUPERSTEPS": str(supersteps),
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
            "GRASU_SST_EDGE_ARRAY_FIFO_DEPTH": str(
                params["regraph_edge_array_fifo_depth"]
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
                params["regraph_vertex_prop_hbm_channel"]
            ),
            "GRASU_SST_EDGE_ARRAY_CHANNEL": str(
                params["regraph_edge_array_channel"]
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
            "GRASU_SST_AXIS_FIFO_DEPTH": "8",
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
            "GRASU_SST_COMPACTOR_COMPLETION_TOKENS": str(
                params["pma_compactor_completion_tokens"]
            ),
            "GRASU_SST_COMPACTOR_LANE_PIPELINE_LATENCY": str(
                params["pma_compactor_lane_pipeline_latency_cycles"]
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
            f"native SST run failed with rc={completed.returncode}; "
            f"see {args.out_dir / 'sst.log'}"
        )

    result = json.loads(result_path.read_text(encoding="utf-8"))
    validation_profile = json.loads(json.dumps(profile))
    validation_profile["parameters"]["native_validation_supersteps"] = supersteps
    validate_result(result, validation_profile, args.source)
    manifest = {
        "schema_version": 1,
        "claim_class": "native_structural_simulation",
        "algorithm": algorithm_capability.algorithm,
        "algorithm_capability": algorithm_capability.manifest_record(),
        "capability_catalog": str(capability_catalog.manifest_path),
        "capability_catalog_sha256": capability_catalog.manifest_sha256,
        "profile": str(profile_path),
        "profile_sha256": sha256(profile_path),
        "workload": str(args.workload.resolve()),
        "workload_sha256": sha256(args.workload.resolve()),
        "update_workload": str(args.update_workload.resolve()),
        "update_workload_sha256": sha256(args.update_workload.resolve()),
        "hardware_evidence": profile.get("evidence", []),
        "source_external": args.source,
        "source_internal": result["source_internal"],
        "supersteps": supersteps,
        "sst_memory_binding": {
            "physical_channels": memory["channels"],
            "hls_reachable_channels": list(active_channels),
            "instantiated_channels": list(instantiated_channels),
            "unbound_request_policy": "fatal",
            "claim": (
                "host_runtime_optimization_only_physical_architecture_unchanged"
            ),
        },
        "command": command,
        "result": result,
        "status": "PASS",
    }
    (args.out_dir / "manifest.json").write_text(
        json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    print(
        "PASS grasu_regraph_native_sst: "
        f"cycles={result['cycles']} update={result['update_cycles']} "
        f"conversion={result['conversion_cycles']} "
        f"compute={result['compute_cycles']}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
