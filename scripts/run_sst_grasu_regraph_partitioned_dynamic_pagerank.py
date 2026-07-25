#!/usr/bin/env python3
"""Run partitioned GraSU update + PMA-native ReGraph PageRank on SST-HBM."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import subprocess
import time


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_SST = Path("/data/feiyang/sst/bin/sst")
DEFAULT_PROFILE = (
    ROOT
    / "configs"
    / "architectures"
    / "grasu_regraph_partitioned_dynamic_pagerank_spine23.json"
)
NORMALIZED_INITIAL = (
    ROOT / "tests" / "data" / "grasu_regraph_partitioned_normalized_initial.slice"
)
NORMALIZED_UPDATE = (
    ROOT / "tests" / "data" / "grasu_regraph_partitioned_normalized_update.slice"
)
SMOKE_INITIAL = (
    ROOT / "tests" / "data" / "grasu_regraph_partitioned_dynamic_initial.slice"
)
SMOKE_UPDATE = (
    ROOT / "tests" / "data" / "grasu_regraph_partitioned_dynamic_update.slice"
)


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for block in iter(lambda: source.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def load_slice(path: Path) -> tuple[int, list[tuple[int, int, int, int]]]:
    vertices = None
    edges: list[tuple[int, int, int, int]] = []
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if line.startswith("# vertices="):
            vertices = int(line.split("=", 1)[1])
        elif line and not line.startswith("#"):
            src, dst, weight, diff = (int(value) for value in line.split())
            edges.append((src, dst, weight, diff))
    if vertices is None or vertices <= 0:
        raise ValueError(f"missing positive vertex count in {path}")
    return vertices, edges


def expected_update_summary(
    initial_path: Path, update_path: Path, partition_vertices: int
) -> dict[str, int]:
    vertices, initial = load_slice(initial_path)
    update_vertices, updates = load_slice(update_path)
    if update_vertices != vertices:
        raise ValueError("initial and update vertex counts differ")
    live = {(src, dst): weight for src, dst, weight, diff in initial if diff == 1}
    inserts = deletes = decreases = increases = 0
    touched: set[int] = set()
    for src, dst, weight, diff in updates:
        touched.add(dst // partition_vertices)
        key = (src, dst)
        if diff == -1:
            if live.get(key) != weight:
                raise ValueError(f"delete misses live weighted edge {key}")
            del live[key]
            deletes += 1
        elif diff == 1:
            previous = live.get(key)
            if previous is None:
                inserts += 1
            elif weight < previous:
                decreases += 1
            elif weight > previous:
                increases += 1
            else:
                raise ValueError(f"update does not change edge {key}")
            live[key] = weight
        else:
            raise ValueError("GraSU update diff must be +1 or -1")
    return {
        "vertices": vertices,
        "initial_edges": len(initial),
        "updates": len(updates),
        "final_edges": len(live),
        "inserts": inserts,
        "deletes": deletes,
        "weight_decreases": decreases,
        "weight_increases": increases,
        "partitions_touched": len(touched),
    }


def partition_layout_footprints(
    initial_path: Path, update_path: Path, partition_vertices: int
) -> list[dict[str, int]]:
    vertices, initial = load_slice(initial_path)
    update_vertices, updates = load_slice(update_path)
    if update_vertices != vertices:
        raise ValueError("initial and update vertex counts differ")
    partitions = (vertices + partition_vertices - 1) // partition_vertices
    reserved: list[dict[int, set[int]]] = [dict() for _ in range(partitions)]
    for src, dst, _weight, diff in initial + updates:
        if diff != 1:
            continue
        partition = dst // partition_vertices
        reserved[partition].setdefault(src, set()).add(dst % partition_vertices)
    footprints = []
    for partition, rows in enumerate(reserved):
        segments = sum((len(destinations) + 15) // 16 for destinations in rows.values())
        footprints.append(
            {
                "partition": partition,
                "row_bytes": vertices * 8,
                "binary_bytes": segments * 8,
                "pma_bytes_per_channel": ((segments + 1) // 2) * 64,
                "segments": segments,
            }
        )
    return footprints


def validate_partition_footprints(
    params: dict[str, object], footprints: list[dict[str, int]]
) -> None:
    stride = int(params["grasu_partition_address_stride_bytes"])
    for footprint in footprints:
        for field in ("row_bytes", "binary_bytes", "pma_bytes_per_channel"):
            if footprint[field] > stride:
                raise ValueError(
                    f"partition {footprint['partition']} {field} exceeds "
                    "the frozen partition address stride"
                )


def load_dram_stats(dram_dir: Path) -> dict[str, int | float]:
    totals: dict[str, int | float] = {
        "channels": 0,
        "reads": 0,
        "writes": 0,
        "activates": 0,
        "precharges": 0,
        "read_row_hits": 0,
        "write_row_hits": 0,
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
        totals["read_row_hits"] += int(row["num_read_row_hits"])
        totals["write_row_hits"] += int(row["num_write_row_hits"])
        totals["total_energy_pj"] += float(row["total_energy"])
    return totals


def validate_address_map(
    params: dict[str, object],
    channel_bytes: int,
    destination_partitions: int,
    vertices: int,
    updates: int,
) -> dict[str, list[int]]:
    stride = int(params["grasu_partition_address_stride_bytes"])
    regions = {
        "update": [int(params["grasu_update_base_bytes"]), updates * 16],
        "binary": [
            int(params["grasu_binary_base_bytes"]),
            destination_partitions * stride,
        ],
        "row": [
            int(params["grasu_row_offset_base_bytes"]),
            destination_partitions * stride,
        ],
        "pma": [
            int(params["grasu_pma_base_bytes"]),
            destination_partitions * stride,
        ],
        "source_state": [
            int(params["grasu_source_state_base_bytes"]),
            2 * int(params["grasu_source_state_buffer_stride_bytes"])
            + vertices * 4,
        ],
        "vertex_state": [int(params["grasu_vertex_state_base_bytes"]), vertices * 4],
        "degree": [int(params["grasu_degree_base_bytes"]), vertices * 4],
    }

    def overlap(left: list[int], right: list[int]) -> bool:
        return max(left[0], right[0]) < min(
            left[0] + left[1], right[0] + right[1]
        )

    for name, (base, size) in regions.items():
        if size <= 0 or base < 0 or base + size > channel_bytes:
            raise ValueError(f"{name} physical address window exceeds one HBM channel")
    shared = ["update", "binary", "row", "pma"]
    for left_index, left in enumerate(shared):
        for right in shared[left_index + 1 :]:
            if overlap(regions[left], regions[right]):
                raise ValueError(f"physical HBM windows overlap: {left}, {right}")
    for shared_name in shared:
        if overlap(regions[shared_name], regions["source_state"]):
            raise ValueError(
                f"source-state window overlaps channel-1/3 {shared_name} window"
            )
    if overlap(regions["vertex_state"], regions["degree"]):
        raise ValueError("vertex-state and degree windows overlap on channel 30")
    return regions


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--profile", type=Path, default=DEFAULT_PROFILE)
    parser.add_argument("--initial", type=Path)
    parser.add_argument("--update", type=Path)
    parser.add_argument("--out-dir", type=Path, required=True)
    parser.add_argument("--sst", type=Path, default=DEFAULT_SST)
    parser.add_argument("--lib-dir", type=Path, default=ROOT / "build" / "sst")
    parser.add_argument("--max-cycles", type=int, default=5_000_000)
    parser.add_argument(
        "--smoke",
        action="store_true",
        help="Use 33 vertices and 16-vertex partitions for a fast component run.",
    )
    parser.add_argument("--no-build", action="store_true")
    args = parser.parse_args()
    if args.max_cycles <= 0:
        raise ValueError("max-cycles must be positive")

    profile_path = args.profile.resolve()
    profile = json.loads(profile_path.read_text(encoding="utf-8"))
    expected_profile = "grasu_regraph_partitioned_dynamic_pagerank_spine23"
    if profile.get("profile_id") != expected_profile:
        raise ValueError("runner requires the partitioned dynamic PageRank profile")
    params = profile["parameters"]
    memory = profile["memory"]
    kernel_clock = next(
        clock for clock in profile["clocks"] if clock["name"] == "kernel"
    )
    initial_path = (args.initial or (SMOKE_INITIAL if args.smoke else NORMALIZED_INITIAL)).resolve()
    update_path = (args.update or (SMOKE_UPDATE if args.smoke else NORMALIZED_UPDATE)).resolve()
    partition_vertices = (
        16 if args.smoke else int(params["regraph_destination_partition_vertices"])
    )
    expected = expected_update_summary(initial_path, update_path, partition_vertices)
    layout_footprints = partition_layout_footprints(
        initial_path, update_path, partition_vertices
    )
    validate_partition_footprints(params, layout_footprints)
    if expected["updates"] > int(params["grasu_degree_reorder_entries"]):
        raise ValueError("update batch exceeds the degree reorder scoreboard")
    iterations = int(params["pagerank_iterations"])
    destination_partitions = (
        expected["vertices"] + partition_vertices - 1
    ) // partition_vertices
    if destination_partitions > params["max_destination_partitions_without_address_remap"]:
        raise ValueError("workload exceeds the frozen profile's physical address map")
    address_regions = validate_address_map(
        params,
        int(memory["channel_capacity_bytes"]),
        destination_partitions,
        expected["vertices"],
        expected["updates"],
    )

    if not args.no_build:
        subprocess.run(["make", "-C", "cpp/sst", "-j2"], cwd=ROOT, check=True)
    library_path = (args.lib_dir / "libspine_cycle.so").resolve()
    if not library_path.is_file():
        raise FileNotFoundError(library_path)

    args.out_dir.mkdir(parents=True, exist_ok=True)
    result_path = (args.out_dir / "result.json").resolve()
    dram_dir = (args.out_dir / "dram").resolve()
    if result_path.exists() or dram_dir.exists():
        raise FileExistsError("out-dir already contains result.json or dram/")
    env = os.environ.copy()
    env.update(
        {
            "GRASU_SST_MODE": "grasu_regraph_partitioned_dynamic_pagerank",
            "GRASU_SST_CHANNELS": str(memory["channels"]),
            "GRASU_SST_CHANNEL_BYTES": str(memory["channel_capacity_bytes"]),
            "GRASU_SST_WORKLOAD": str(initial_path),
            "GRASU_SST_UPDATE_WORKLOAD": str(update_path),
            "GRASU_SST_OUTPUT": str(result_path),
            "GRASU_SST_DRAM_OUTPUT": str(dram_dir),
            "GRASU_SST_CORE_MHZ": str(kernel_clock["achieved_mhz"]),
            "GRASU_SST_MAX_CYCLES": str(args.max_cycles),
            "GRASU_SST_PAGERANK_ITERATIONS": str(iterations),
            "GRASU_SST_PAGERANK_DAMPING": str(params["pagerank_damping"]),
            "GRASU_SST_CACHE_SEGMENTS_PER_HALF": str(
                params["grasu_cache_segments_per_cu"]
            ),
            "GRASU_SST_PARTITION_VERTICES": str(partition_vertices),
            "GRASU_SST_UPDATE_BASE": str(params["grasu_update_base_bytes"]),
            "GRASU_SST_BINARY_BASE": str(params["grasu_binary_base_bytes"]),
            "GRASU_SST_ROW_OFFSET_BASE": str(
                params["grasu_row_offset_base_bytes"]
            ),
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
            "GRASU_SST_DEGREE_FIFO_DEPTH": str(params["grasu_degree_fifo_depth"]),
            "GRASU_SST_DEGREE_REORDER_ENTRIES": str(
                params["grasu_degree_reorder_entries"]
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
    command = [
        str(args.sst.resolve()),
        f"--add-lib-path={args.lib_dir.resolve()}",
        str(ROOT / "sst" / "grasu_regraph_vertical.py"),
    ]
    wall_start = time.monotonic()
    completed = subprocess.run(
        command,
        cwd=ROOT,
        env=env,
        check=False,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
    )
    wall_seconds = time.monotonic() - wall_start
    (args.out_dir / "sst.log").write_text(completed.stdout, encoding="utf-8")
    if completed.returncode != 0:
        raise RuntimeError(
            f"SST partitioned dynamic PageRank failed with rc={completed.returncode}; "
            f"see {args.out_dir / 'sst.log'}"
        )

    result = json.loads(result_path.read_text(encoding="utf-8"))
    dram = load_dram_stats(dram_dir)
    expected_claim = (
        "component_validation_simulation" if args.smoke else "normalized_simulation"
    )
    partition_passes = destination_partitions * iterations
    expected_rows = expected["vertices"] * partition_passes
    expected_gather_rows = partition_vertices // 2 * partition_passes
    expected_bursts = partition_vertices // 16 * partition_passes
    degree_updates = expected["inserts"] + expected["deletes"]
    expected_update_requests = sum(
        result.get(field, -1)
        for field in (
            "updates",
            "update_row_reads",
            "update_binary_probes",
            "update_pma_reads",
            "update_pma_writes",
            "degree_update_reads",
            "degree_update_writes",
        )
    )
    expected_compute_requests = sum(
        result.get(field, -1)
        for field in (
            "compute_row_reads",
            "source_cache_lines",
            "degree_reads",
            "compute_pma_segment_reads",
            "apply_state_reads",
            "apply_state_writes",
            "compute_source_state_writes",
        )
    )
    expected_update_read_bytes = sum(
        result.get(field, -1)
        for field in (
            "update_record_read_bytes",
            "update_row_read_bytes",
            "update_binary_read_bytes",
            "update_pma_read_bytes",
            "degree_update_read_bytes",
        )
    )
    expected_update_write_bytes = result.get("update_pma_write_bytes", -1) + result.get(
        "degree_update_write_bytes", -1
    )
    expected_compute_read_bytes = sum(
        result.get(field, -1)
        for field in (
            "row_read_bytes",
            "source_state_read_bytes",
            "degree_read_bytes",
            "pma_read_bytes",
            "apply_read_bytes",
        )
    )
    expected_compute_write_bytes = result.get("apply_write_bytes", -1) + result.get(
        "source_state_write_bytes", -1
    )
    expected_dram_reads = expected_update_requests - result["update_pma_writes"] - result["degree_update_writes"] + (
        expected_compute_requests
        - result["apply_state_writes"]
        - result["compute_source_state_writes"]
    )
    expected_dram_writes = (
        result["update_pma_writes"]
        + result["degree_update_writes"]
        + result["apply_state_writes"]
        + result["compute_source_state_writes"]
    )

    if (
        not result.get("success")
        or result.get("mode") != "grasu_regraph_partitioned_dynamic_pagerank"
        or result.get("claim_class") != expected_claim
        or result.get("correctness_mismatches") != 0
        or result.get("architecture_correctness_mismatches") != 0
        or result.get("mathematical_correctness_mismatches") != 0
        or result.get("update_state_mismatches") != 0
        or result.get("degree_state_mismatches") != 0
        or result.get("max_abs_error", 1.0) > 1.0e-5
        or result.get("mathematical_max_abs_error", 1.0) > 1.0e-5
        or abs(result.get("rank_sum", 0.0) - 1.0) > 1.0e-4
        or result.get("vertices") != expected["vertices"]
        or result.get("initial_edges") != expected["initial_edges"]
        or result.get("updates") != expected["updates"]
        or result.get("update_inserts") != expected["inserts"]
        or result.get("update_deletes") != expected["deletes"]
        or result.get("update_weight_decreases") != expected["weight_decreases"]
        or result.get("update_weight_increases") != expected["weight_increases"]
        or result.get("update_record_bytes") != params["grasu_update_record_bytes"]
        or result.get("destination_partitions") != destination_partitions
        or result.get("destination_partitions_touched") != expected["partitions_touched"]
        or result.get("partition_routes") != expected["updates"]
        or result.get("partition_passes") != partition_passes
        or result.get("iterations") != iterations
        or result.get("degree_update_timing_included") is not True
        or result.get("degree_updates_required") != degree_updates
        or result.get("degree_update_reads") != degree_updates
        or result.get("degree_update_writes") != degree_updates
        or result.get("degree_update_read_bytes") != 4 * degree_updates
        or result.get("degree_update_write_bytes") != 4 * degree_updates
        or not 0 < result.get("degree_fifo_max_occupancy", 0) <= params["grasu_degree_fifo_depth"]
        or not 0 < result.get("degree_reorder_max_occupancy", 0) <= min(
            expected["updates"], params["grasu_degree_reorder_entries"]
        )
        or result.get("compute_row_reads") != expected_rows
        or result.get("compute_live_edges") != expected["final_edges"] * iterations
        or result.get("compute_active_edges") != expected["final_edges"] * iterations
        or result.get("gather_bank_updates") != result.get("compute_active_edges")
        or result.get("gather_rows_emitted") != expected_gather_rows
        or result.get("merger_rows_consumed") != expected_gather_rows
        or result.get("merger_bursts_emitted") != expected_bursts
        or result.get("apply_state_reads") != expected_bursts
        or result.get("apply_state_writes") != expected_bursts
        or result.get("apply_input_bursts") != expected_bursts
        or result.get("hbm_wrapper_input_bursts") != expected_bursts
        or result.get("compute_source_state_writes") != 2 * expected_bursts
        or result.get("source_map_cycles")
        != result.get("degree_reads", -1) * params["regraph_pagerank_source_map_latency"]
        or result.get("update_read_bytes") != expected_update_read_bytes
        or result.get("update_write_bytes") != expected_update_write_bytes
        or result.get("compute_read_bytes") != expected_compute_read_bytes
        or result.get("compute_write_bytes") != expected_compute_write_bytes
        or result.get("update_backend_requests") != expected_update_requests
        or result.get("compute_backend_requests") != expected_compute_requests
        or result.get("expected_backend_requests")
        != expected_update_requests + expected_compute_requests
        or result.get("backend_requests") != result.get("expected_backend_requests")
        or result.get("cycles")
        != result.get("update_cycles", -1) + result.get("compute_cycles", -1)
        or result.get("serial_unattributed_cycles") != 0
        or dram["channels"] != memory["channels"]
        or dram["reads"] != expected_dram_reads
        or dram["writes"] != expected_dram_writes
        or dram["reads"] + dram["writes"] != result.get("backend_requests")
    ):
        raise RuntimeError(
            f"SST partitioned dynamic PageRank validation failed: {result}; dram={dram}"
        )

    manifest = {
        "schema_version": 1,
        "profile": str(profile_path),
        "profile_sha256": sha256(profile_path),
        "initial_workload": str(initial_path),
        "initial_workload_sha256": sha256(initial_path),
        "update_workload": str(update_path),
        "update_workload_sha256": sha256(update_path),
        "simulator_library": str(library_path),
        "simulator_library_sha256": sha256(library_path),
        "smoke": args.smoke,
        "command": command,
        "expected": expected,
        "physical_address_regions": address_regions,
        "partition_layout_footprints": layout_footprints,
        "result": result,
        "dram": dram,
        "wall_seconds": wall_seconds,
        "status": "PASS",
    }
    (args.out_dir / "manifest.json").write_text(
        json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    print(
        "PASS grasu_regraph_partitioned_dynamic_pagerank_sst: "
        f"claim={result['claim_class']} cycles={result['cycles']} "
        f"partitions={destination_partitions} requests={result['backend_requests']} "
        f"dram_energy_pj={dram['total_energy_pj']} wall_seconds={wall_seconds:.3f}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
