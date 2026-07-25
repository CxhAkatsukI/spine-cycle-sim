#!/usr/bin/env python3
"""Run the existing-HLS GraSU -> compactor -> ReGraph native SST baseline."""

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
    ROOT / "configs" / "architectures" / "grasu_regraph_native_a9aef06.json"
)


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for block in iter(lambda: source.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def native_active_hbm_channels(profile: dict[str, object]) -> tuple[int, ...]:
    """Derive the HBM channels reachable by the pinned native HLS topology."""

    memory = profile.get("memory")
    params = profile.get("parameters")
    if not isinstance(memory, dict) or not isinstance(params, dict):
        raise ValueError("native profile requires memory and parameters objects")
    physical_channels = int(memory["channels"])
    first_pma = int(params["grasu_pma_hbm_first_channel"])
    pma_channels = int(params["grasu_pma_hbm_channels"])
    active = set(range(first_pma, first_pma + pma_channels))
    for field in (
        "pma_compactor_row_channel",
        "regraph_edge_array_channel",
        "regraph_source_state_channel",
        "regraph_source_state_mirror_channel",
        "regraph_vertex_prop_hbm_channel",
    ):
        active.add(int(params[field]))
    ordered = tuple(sorted(active))
    if not ordered or ordered[0] < 0 or ordered[-1] >= physical_channels:
        raise ValueError(
            "native HLS topology references an out-of-range HBM channel"
        )
    return ordered


def validate_result(
    result: dict[str, object],
    profile: dict[str, object],
    expected_source_external: int | None = None,
) -> None:
    params = profile["parameters"]
    assert isinstance(params, dict)
    supersteps = int(result.get("supersteps", -1))
    compact_slots = int(result.get("compact_edge_slots", -1))
    final_edges = int(result.get("final_edges", -1))
    vertices = int(result.get("vertices", -1))
    apply_bursts = params["regraph_partition_vertices"] // 16 * supersteps
    expected_edge_bursts = compact_slots // 8 * supersteps
    checks = {
        "success": result.get("success") is True,
        "mode": result.get("mode") == "grasu_regraph_native_sssp",
        "claim": result.get("claim_class") == "native_structural_simulation",
        "backend": result.get("backend") == "sst_memHierarchy_dramsim3",
        "conversion": result.get("conversion_cost_included") is True,
        "host_reorder": result.get("native_host_vertex_reorder") is True,
        "source_alias": result.get("source") == result.get("source_internal"),
        "source_external": expected_source_external is None
        or result.get("source_external") == expected_source_external,
        "serial_order": result.get("pipeline_order")
        == "update_then_barrier_compactor_then_compute",
        "ledger": result.get("cycles")
        == result.get("component_cycles", -1) + result.get("controller_gap_cycles", -2),
        "correctness": result.get("correctness_mismatches") == 0,
        "hls_contract": result.get("native_hls_contract_safe") is True,
        "cross_window": result.get("cross_source_round_bursts") == 0,
        "abi": result.get("pma_edge_abi") == "native_raw_destination32",
        "supersteps": supersteps == params["native_validation_supersteps"],
        "barrier_tokens": result.get("completion_token_reads")
        == params["pma_compactor_completion_tokens"],
        "barrier_cycles": result.get("barrier_cycles")
        == params["pma_compactor_completion_tokens"],
        "row_scan": result.get("compactor_row_reads") == vertices + 1,
        "pma_scan": result.get("compactor_pma_slots_scanned")
        == result.get("pma_slots"),
        "valid_edges": result.get("compactor_valid_edges") == final_edges,
        "dummy_edges": result.get("compactor_dummy_edge_slots")
        == compact_slots - final_edges,
        "edge_writes": result.get("compactor_edge_array_writes")
        == compact_slots // 8,
        "edge_requests": result.get("edge_array_requests") == supersteps,
        "edge_bursts": result.get("edge_array_bursts") == expected_edge_bursts,
        "edge_slots": result.get("edge_array_slots_scanned")
        == compact_slots * supersteps,
        "edge_bytes": result.get("edge_array_read_bytes")
        == compact_slots * 8 * supersteps,
        "apply_reads": result.get("apply_state_reads") == apply_bursts,
        "apply_writes": result.get("apply_state_writes") == apply_bursts,
        "source_mirrors": result.get("compute_source_state_writes")
        == params["regraph_source_state_copies"] * apply_bursts,
    }
    failed = [name for name, passed in checks.items() if not passed]
    if failed:
        raise RuntimeError(f"native SST validation failed ({failed}): {result}")


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
