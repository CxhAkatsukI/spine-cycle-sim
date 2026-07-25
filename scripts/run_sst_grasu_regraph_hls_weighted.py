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
from spine_cycle_sim.experiments.regraph_contracts import (  # noqa: E402
    expected_weighted_source_cache_requests,
)
from spine_cycle_sim.experiments.shared_workloads import (  # noqa: E402
    SliceGraph,
    load_slice,
)
from spine_cycle_sim.sst_binding import grasu_normalized_memory_binding  # noqa: E402


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


def require_hls_weighted_capability(
    profile_path: Path, capability_catalog_path: Path
) -> tuple[CapabilityCatalog, AlgorithmCapability]:
    profile = json.loads(profile_path.read_text(encoding="utf-8"))
    profile_id = str(profile.get("profile_id", ""))
    catalog = load_capability_catalog(capability_catalog_path)
    profile_capability = catalog.profile(profile_id)
    if profile_capability.profile_path != profile_path.resolve():
        raise ValueError("weighted-HLS capability profile path does not match")
    capability = profile_capability.require("weighted_dynamic_sssp")
    if (
        profile_capability.comparison_role != "hls_sw_emu"
        or profile_capability.handoff != "weighted_pma_to_axis_stream"
        or profile_capability.conversion_cost != "absent"
    ):
        raise ValueError("capability does not describe the ff13a67 HLS path")
    return catalog, capability


def _dijkstra(
    vertices: int, edges: tuple[tuple[int, int, int], ...], source: int
) -> tuple[int, ...]:
    adjacency: list[list[tuple[int, int]]] = [[] for _ in range(vertices)]
    for src, dst, weight in edges:
        adjacency[src].append((dst, weight))
    unreachable = 1 << 63
    distances = [unreachable] * vertices
    distances[source] = 0
    pending: list[tuple[int, int]] = [(0, source)]
    while pending:
        distance, vertex = heapq.heappop(pending)
        if distance != distances[vertex]:
            continue
        for destination, weight in adjacency[vertex]:
            candidate = distance + weight
            if candidate < distances[destination]:
                distances[destination] = candidate
                heapq.heappush(pending, (candidate, destination))
    return tuple(HLS_INFINITY if value == unreachable else value for value in distances)


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
    return HlsWeightedOracle(
        logical_updates=len(update.records),
        physical_updates=sum(physical_counts),
        external_to_internal=external_to_internal,
        internal_to_external=internal_to_external,
        final_external_edges=external_edges,
        final_internal_edges=internal_edges,
        external_distances=_dijkstra(vertices, external_edges, source_external),
        source_internal=external_to_internal[source_external],
    )


def validate_result(
    result: dict[str, object],
    profile: dict[str, object],
    oracle: HlsWeightedOracle,
) -> None:
    params = profile["parameters"]
    assert isinstance(params, dict)
    supersteps = int(params["hls_validation_supersteps"])
    partition_vertices = int(params["regraph_partition_vertices"])
    source_buffer_vertices = int(params["regraph_source_buffer_vertices"])
    max_internal_source = max(src for src, _, _ in oracle.final_internal_edges)
    expected_source_requests = expected_weighted_source_cache_requests(
        max_internal_source, source_buffer_vertices, supersteps
    )
    expected_source_lines = expected_source_requests * source_buffer_vertices // 16
    expected_rows = partition_vertices // 2 * supersteps
    expected_bursts = partition_vertices // 16 * supersteps
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
        raise RuntimeError(f"weighted-HLS SST validation failed ({failed}): {result}")


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
    parser.add_argument("--out-dir", type=Path, required=True)
    parser.add_argument("--sst", type=Path, default=DEFAULT_SST)
    parser.add_argument("--lib-dir", type=Path, default=ROOT / "build" / "sst")
    parser.add_argument("--max-cycles", type=int, default=30_000_000)
    parser.add_argument("--no-build", action="store_true")
    parser.add_argument("--instantiate-all-hbm-channels", action="store_true")
    args = parser.parse_args()

    profile_path = args.profile.resolve()
    profile = json.loads(profile_path.read_text(encoding="utf-8"))
    expected_profile_id = "grasu_regraph_weighted_pma_hls_sw_emu_ff13a67"
    if profile.get("profile_id") != expected_profile_id:
        raise ValueError("runner requires the pinned ff13a67 weighted-HLS profile")
    capability_catalog, algorithm_capability = require_hls_weighted_capability(
        profile_path, args.capability_catalog.resolve()
    )
    params = profile["parameters"]
    memory = profile["memory"]
    supersteps = args.supersteps or int(params["hls_validation_supersteps"])
    if supersteps != int(params["hls_validation_supersteps"]):
        raise ValueError("ff13a67 evidence mode requires the pinned superstep count")
    for evidence in profile.get("evidence", []):
        path = Path(evidence["path"])
        if not path.is_file() or sha256(path) != evidence["sha256"]:
            raise RuntimeError(f"weighted-HLS profile evidence mismatch: {path}")
    initial = load_slice(args.workload.resolve())
    update = load_slice(args.update_workload.resolve())
    oracle = build_hls_weighted_oracle(initial, update, args.source)
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
            f"weighted-HLS SST failed with rc={completed.returncode}; "
            f"see {args.out_dir / 'sst.log'}"
        )
    result = json.loads(result_path.read_text(encoding="utf-8"))
    validate_result(result, profile, oracle)
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
        "sst_host_wall_seconds": wall_seconds,
        "oracle": {
            "logical_updates": oracle.logical_updates,
            "physical_updates": oracle.physical_updates,
            "external_to_internal": list(oracle.external_to_internal),
            "external_distances": list(oracle.external_distances),
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
        "PASS grasu_regraph_hls_weighted_sst: "
        f"cycles={result['cycles']} update={result['update_cycles']} "
        f"compute={result['compute_cycles']} logical={oracle.logical_updates} "
        f"physical={oracle.physical_updates} wall_s={wall_seconds:.3f}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
