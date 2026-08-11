#!/usr/bin/env python3
"""Run one correctness-gated dynamic CC case on SST-HBM."""

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

from spine_cycle_sim.experiments.connected_components_workloads import (  # noqa: E402
    ReciprocalUpdateAnalysis,
    analyze_reciprocal_update,
    connected_components_labels,
    materialize_reciprocal_update,
)
from spine_cycle_sim.experiments.grasu_addressing import (  # noqa: E402
    grasu_hbm_address_environment,
    partition_layout_footprints,
    selected_source_state_stride_bytes,
    validate_grasu_hbm_address_map,
    validate_partition_footprints,
)
from spine_cycle_sim.experiments.host_memory import release_process_heap  # noqa: E402
from spine_cycle_sim.experiments.profile_capabilities import (  # noqa: E402
    load_capability_catalog,
)
from spine_cycle_sim.experiments.shared_workloads import (  # noqa: E402
    load_slice,
    sha256_file,
)
from spine_cycle_sim.sst_binding import (  # noqa: E402
    grasu_normalized_memory_binding,
    spine_memory_binding,
)
from spine_cycle_sim.sst_library import forced_sst_library_binding  # noqa: E402
from scripts.run_sst_grasu_regraph import load_dram_stats  # noqa: E402


DEFAULT_WORKLOAD = ROOT / "tests/data/connected_components_bridge_initial.slice"
DEFAULT_UPDATE = ROOT / "tests/data/connected_components_bridge_insert.slice"
DEFAULT_SST = Path("/data/feiyang/sst/bin/sst")
DEFAULT_LIB_DIR = ROOT / "build/sst"
DEFAULT_SPINE_PROFILE = (
    ROOT / "configs/architectures/spine_candidate10_opt_v2_reader_working_set.json"
)
DEFAULT_CAPABILITY_CATALOG = (
    ROOT / "configs/contracts/grasu_regraph_publication_capabilities_v6.json"
)
DEFAULT_SST_INSTALL_PREFIX = Path(
    "/data/tmp/chuxiao/candidate59-cleanpatch-reproduction-install-20260729"
)
DEFAULT_DRAMSIM3_SRC = Path(
    "/data/tmp/chuxiao/candidate73-dramsim3-pgo-src-20260729"
)


def _with_progress_defaults(
    environment: dict[str, str], out_dir: Path
) -> dict[str, str]:
    environment.setdefault(
        "SPINE_CAMPAIGN_PROGRESS_PATH",
        str((out_dir / "progress.json").resolve()),
    )
    environment.setdefault("SPINE_CAMPAIGN_PROGRESS_INTERVAL_CYCLES", "1000000")
    return environment


def _default_grasu_profile(compute_pipelines: int, sharing: str) -> Path:
    if compute_pipelines == 1 and sharing == "direct":
        name = "grasu_regraph_candidate10_k1_multipart_cc_packed_v6.json"
    elif compute_pipelines == 4 and sharing == "direct":
        name = "grasu_regraph_candidate10_k4_multipart_cc_packed_v6.json"
    elif compute_pipelines == 4 and sharing == "shared":
        name = "grasu_regraph_candidate10_k4_shared_multipart_cc_packed_v6.json"
    else:
        raise ValueError(
            "CC publication profiles support K1-direct, K4-direct, and K4-shared"
        )
    return ROOT / "configs/architectures" / name


def _profile_clock(profile: dict[str, Any], name: str) -> float:
    matches = [clock for clock in profile["clocks"] if clock["name"] == name]
    if len(matches) != 1:
        raise ValueError(f"CC profile lacks one {name} clock")
    return float(matches[0]["achieved_mhz"])


def _spine_profile_environment(parameters: dict[str, Any]) -> dict[str, str]:
    mapping = {
        "range_task_active_gate": "SPINE_SST_RANGE_TASK_ACTIVE_GATE",
        "axi_profile": "SPINE_SST_AXI_PROFILE",
        "maintenance_architecture": "SPINE_SST_MAINTENANCE_ARCHITECTURE",
        "l0_writer_base_residual_cycles": (
            "SPINE_SST_CANDIDATE_L0_WRITER_BASE_RESIDUAL_CYCLES"
        ),
        "l0_writer_single_record_cycles": (
            "SPINE_SST_CANDIDATE_L0_WRITER_SINGLE_RECORD_CYCLES"
        ),
        "l0_writer_late_source_cycles": (
            "SPINE_SST_CANDIDATE_L0_WRITER_LATE_SOURCE_CYCLES"
        ),
        "l0_writer_packer_cycles": "SPINE_SST_CANDIDATE_L0_WRITER_PACKER_CYCLES",
        "l0_writer_page_tail_cycles": (
            "SPINE_SST_CANDIDATE_L0_WRITER_PAGE_TAIL_CYCLES"
        ),
        "publication_base_cycles": "SPINE_SST_CANDIDATE_PUBLICATION_BASE_CYCLES",
        "publication_source_cycles": (
            "SPINE_SST_CANDIDATE_PUBLICATION_SOURCE_CYCLES"
        ),
        "publication_group_cycles": (
            "SPINE_SST_CANDIDATE_PUBLICATION_GROUP_CYCLES"
        ),
        "publication_new_bit_cycles": (
            "SPINE_SST_CANDIDATE_PUBLICATION_NEW_BIT_CYCLES"
        ),
        "publication_prefetch_restart_cycles": (
            "SPINE_SST_CANDIDATE_PUBLICATION_PREFETCH_RESTART_CYCLES"
        ),
        "publication_empty_base_cycles": (
            "SPINE_SST_CANDIDATE_PUBLICATION_EMPTY_BASE_CYCLES"
        ),
        "publication_empty_group_cycles": (
            "SPINE_SST_CANDIDATE_PUBLICATION_EMPTY_GROUP_CYCLES"
        ),
        "publication_full_window_rebate_cycles": (
            "SPINE_SST_CANDIDATE_PUBLICATION_FULL_WINDOW_REBATE_CYCLES"
        ),
        "publication_next_window_overlap_cycles": (
            "SPINE_SST_CANDIDATE_PUBLICATION_NEXT_WINDOW_OVERLAP_CYCLES"
        ),
        "max_vertices": "SPINE_SST_OWNER_MAX_VERTICES",
        "partitions": "SPINE_SST_OWNER_PARTITIONS",
        "vertex_partition_size": "SPINE_SST_OWNER_VERTICES_PER_PARTITION",
        "owner_fifo_depth_per_partition": "SPINE_SST_OWNER_FIFO_DEPTH",
        "reactivation_fifo_depth_per_partition": (
            "SPINE_SST_REACTIVATION_FIFO_DEPTH"
        ),
    }
    environment = {
        environment_name: str(parameters[parameter])
        for parameter, environment_name in mapping.items()
        if parameter in parameters
    }
    environment.update(
        {
            "SPINE_SST_FALLBACK_LEVEL_CACHE_REUSE": str(
                int(bool(parameters.get("fallback_level_cache_reuse", False)))
            ),
            "SPINE_SST_SOURCE_PAGE_INDEX_CACHE": str(
                int(bool(parameters.get("source_page_index_cache", False)))
            ),
            "SPINE_SST_CANDIDATE_L0_WRITER_RTL_SCHEDULE": str(
                int(bool(parameters.get("l0_writer_rtl_schedule", True)))
            ),
            "SPINE_SST_OWNER_SCHEDULER_ENABLED": str(
                int(bool(parameters.get("owner_scheduler_enabled", False)))
            ),
        }
    )
    return environment


def expected_update_mode(
    analysis: ReciprocalUpdateAnalysis,
    *,
    hardware_full_recompute: bool = False,
) -> str:
    if hardware_full_recompute:
        return "hardware_full_recompute"
    if analysis.zero_net:
        return "zero_net_no_repair"
    if analysis.deletions:
        return "deletion_full_recompute"
    return "insertion_incremental_repair"


def validate_result(
    result: dict[str, Any],
    *,
    architecture: str,
    expected_labels: tuple[int, ...],
    analysis: ReciprocalUpdateAnalysis,
    compute_pipelines: int,
    downstream_sharing: str,
    hardware_full_recompute: bool = False,
) -> dict[str, bool]:
    expected_mode = (
        "spine_connected_components"
        if architecture == "spine"
        else "grasu_regraph_connected_components"
    )
    labels = tuple(int(value) for value in result.get("labels", []))
    checks = {
        "success": result.get("success") is True,
        "mode": result.get("mode") == expected_mode,
        "algorithm_contract": result.get("algorithm_contract")
        == "weakly_connected_min_vertex_reciprocal_v1",
        "dual_oracle": result.get("architecture_correctness_mismatches") == 0
        and result.get("mathematical_correctness_mismatches") == 0
        and result.get("correctness_mismatches") == 0,
        "external_labels": labels == expected_labels,
        "converged": result.get("converged") is True
        and bool(result.get("frontier_out_sizes"))
        and result["frontier_out_sizes"][-1] == 0,
        "update_mode": result.get("update_mode")
        == expected_update_mode(
            analysis,
            hardware_full_recompute=hardware_full_recompute,
        ),
        "effective_mutations": result.get("logical_mutations")
        == analysis.effective_mutations,
        "physical_records": result.get("physical_update_records")
        == analysis.physical_records,
        "active_edge_ledger": result.get("active_edge_execution_ledger_match")
        is True,
        "memory_ledger": result.get("memory_locality_ledger_match") is True,
        "zero_net_no_analytic_work": hardware_full_recompute
        or (not analysis.zero_net)
        or (
            result.get("initial_active_vertices") == 0
            and result.get("active_edges") == 0
        ),
    }
    if architecture == "grasu":
        expected_resident_state = (
            "cold_identity_full_recompute"
            if hardware_full_recompute
            else (
                "cold_identity_deletion_fallback"
                if analysis.deletions
                else "old_graph_converged"
            )
        )
        legacy_k1_downstream = (
            compute_pipelines == 1
            and downstream_sharing == "direct"
            and result.get("downstream_sharing") is None
            and result.get("max_parallel_downstream_partitions") is None
        )
        checks.update(
            {
                "conversion_free": result.get("conversion_cost_included") is False,
                "resident_state": result.get("resident_state")
                == expected_resident_state,
                "pma_state": result.get("update_state_mismatches") == 0,
                "compute_pipelines": result.get("compute_pipelines")
                == compute_pipelines,
                "downstream_sharing": legacy_k1_downstream
                or result.get("downstream_sharing") == downstream_sharing,
                "downstream_parallelism": legacy_k1_downstream
                or result.get("max_parallel_downstream_partitions")
                == (
                    min(compute_pipelines, result.get("destination_partitions", 0))
                    if downstream_sharing == "direct"
                    else 1
                ),
                "partition_work": result.get("partition_passes")
                == result.get("destination_partitions")
                * result.get("iterations"),
            }
        )
    elif result.get("owner_scheduler_enabled") is True:
        checks.update(
            {
                "owner_ledger_closed": result.get("owner_ledger_closed") is True,
                "owner_quiescent": result.get("owner_quiescent") is True,
                "owner_work_credit_ledger": result.get(
                    "owner_work_credits_created"
                )
                == result.get("owner_work_credits_retired"),
                "owner_dispatch_completion_ledger": result.get(
                    "owner_dispatches"
                )
                == result.get("owner_completions"),
                "component_request_ledger": result.get(
                    "component_request_ledger_match"
                )
                is True,
                "fifo_ledger": result.get("fifo_ledger_match") is True,
            }
        )
    return checks


def _git_revision() -> str:
    return subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=ROOT,
        check=True,
        text=True,
        stdout=subprocess.PIPE,
    ).stdout.strip()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--architecture", choices=("spine", "grasu"), required=True)
    parser.add_argument("--workload", type=Path, default=DEFAULT_WORKLOAD)
    parser.add_argument("--update-workload", type=Path, default=DEFAULT_UPDATE)
    parser.add_argument("--out-dir", type=Path, required=True)
    parser.add_argument("--profile", type=Path)
    parser.add_argument(
        "--capability-catalog", type=Path, default=DEFAULT_CAPABILITY_CATALOG
    )
    parser.add_argument("--sst", type=Path, default=DEFAULT_SST)
    parser.add_argument("--lib-dir", type=Path, default=DEFAULT_LIB_DIR)
    parser.add_argument("--wrapper", type=Path)
    parser.add_argument(
        "--sst-install-prefix", type=Path, default=DEFAULT_SST_INSTALL_PREFIX
    )
    parser.add_argument("--dramsim3-src", type=Path, default=DEFAULT_DRAMSIM3_SRC)
    parser.add_argument("--core-mhz", type=float)
    parser.add_argument("--max-cycles", type=int, default=1_000_000_000)
    parser.add_argument("--max-rounds", type=int, default=4096)
    parser.add_argument("--partition-vertices", type=int)
    parser.add_argument("--compute-pipelines", type=int)
    parser.add_argument(
        "--downstream-sharing", choices=("direct", "shared")
    )
    parser.add_argument("--source-buffer-vertices", type=int)
    parser.add_argument("--no-build", action="store_true")
    parser.add_argument("--reuse-result", action="store_true")
    parser.add_argument(
        "--hardware-full-recompute",
        action="store_true",
        help=(
            "Diagnostic cold/full recompute from all-vertex identity labels; "
            "the current resident FPGA matrix does not use this mode."
        ),
    )
    parser.add_argument("--instantiate-all-hbm-channels", action="store_true")
    args = parser.parse_args()
    if args.max_cycles <= 0 or args.max_rounds <= 0:
        raise ValueError("CC runner timing and architecture parameters must be positive")
    if args.hardware_full_recompute and args.architecture != "grasu":
        raise ValueError("hardware full recompute is a G+R FPGA calibration mode")

    requested_pipelines = args.compute_pipelines or 1
    requested_sharing = args.downstream_sharing or "direct"
    profile_path = (
        args.profile.resolve()
        if args.profile is not None
        else DEFAULT_SPINE_PROFILE.resolve()
        if args.architecture == "spine"
        else _default_grasu_profile(
            requested_pipelines, requested_sharing
        ).resolve()
    )
    profile = json.loads(profile_path.read_text(encoding="ascii"))
    expected_architecture = "spine" if args.architecture == "spine" else "grasu_regraph"
    if profile.get("architecture") != expected_architecture:
        raise ValueError("CC architecture and profile do not match")
    parameters = profile["parameters"]
    memory = profile["memory"]
    if args.architecture == "spine":
        compute_pipelines = 1
        downstream_sharing = "native"
        partition_vertices = None
        source_buffer_vertices = None
        core_mhz = args.core_mhz or _profile_clock(profile, "data")
        capability_record = None
    else:
        compute_pipelines = int(parameters["regraph_compute_pipelines"])
        downstream_sharing = str(
            parameters.get("regraph_downstream_sharing", "direct")
        )
        partition_vertices = int(parameters["regraph_partition_vertices"])
        source_buffer_vertices = int(parameters["regraph_source_buffer_vertices"])
        core_mhz = args.core_mhz or _profile_clock(profile, "kernel")
        requested = (
            (args.compute_pipelines, compute_pipelines, "compute pipelines"),
            (args.partition_vertices, partition_vertices, "partition vertices"),
            (
                args.source_buffer_vertices,
                source_buffer_vertices,
                "source-buffer vertices",
            ),
            (args.downstream_sharing, downstream_sharing, "downstream sharing"),
        )
        for explicit, frozen, label in requested:
            if explicit is not None and explicit != frozen:
                raise ValueError(f"CC {label} differs from the frozen profile")
        catalog = load_capability_catalog(args.capability_catalog.resolve())
        capability_profile = catalog.profile(str(profile["profile_id"]))
        if capability_profile.profile_path != profile_path:
            raise ValueError("CC capability profile path does not match")
        capability_record = capability_profile.require(
            "connected_components"
        ).manifest_record()
    if core_mhz <= 0:
        raise ValueError("CC core clock must be positive")

    workload_path = args.workload.resolve()
    update_path = args.update_workload.resolve()
    graph = load_slice(workload_path)
    update = load_slice(update_path)
    analysis = analyze_reciprocal_update(graph, update)
    final_graph = materialize_reciprocal_update(graph, update)
    oracle_labels = connected_components_labels(final_graph)

    if not args.no_build:
        subprocess.run(
            [
                "make",
                "-C",
                "cpp/sst",
                "-j2",
                f"BUILD_DIR={args.lib_dir.resolve()}",
            ],
            cwd=ROOT,
            check=True,
        )
    plugin = args.lib_dir.resolve() / "libspine_cycle.so"
    if not plugin.is_file():
        raise FileNotFoundError(f"missing SST plugin: {plugin}")
    args.out_dir.mkdir(parents=True, exist_ok=True)
    result_path = (args.out_dir / "result.json").resolve()
    log_path = args.out_dir / "sst.log"
    dram_path = (args.out_dir / "dram").resolve()
    if not args.reuse_result:
        result_path.unlink(missing_ok=True)
        shutil.rmtree(dram_path, ignore_errors=True)

    env = _with_progress_defaults(os.environ.copy(), args.out_dir)
    address_regions = None
    runtime_source_state_stride = None
    if args.architecture == "spine":
        binding = spine_memory_binding(
            profile,
            (workload_path, update_path),
            instantiate_all=args.instantiate_all_hbm_channels,
        )
        env.update(
            {
                "SPINE_SST_MODE": "spine_connected_components",
                "SPINE_SST_WORKLOAD": str(workload_path),
                "SPINE_SST_UPDATE_WORKLOAD": str(update_path),
                "SPINE_SST_OUTPUT": str(result_path),
                "SPINE_SST_DRAM_OUTPUT": str(dram_path),
                "SPINE_SST_CHANNELS": str(memory["channels"]),
                "SPINE_SST_ACTIVE_CHANNELS": ",".join(
                    str(value) for value in binding.instantiated_channels
                ),
                "SPINE_SST_CHANNEL_BYTES": str(memory["channel_capacity_bytes"]),
                "SPINE_SST_CORE_MHZ": str(core_mhz),
                "SPINE_SST_MAX_CYCLES": str(args.max_cycles),
                "SPINE_SST_MAX_ROUNDS": str(args.max_rounds),
            }
        )
        env.update(_spine_profile_environment(parameters))
        sst_config = ROOT / "sst/spine_vertical_slice.py"
    else:
        assert partition_vertices is not None
        assert source_buffer_vertices is not None
        binding = grasu_normalized_memory_binding(
            profile, instantiate_all=args.instantiate_all_hbm_channels
        )
        destination_partitions = (
            graph.vertices + partition_vertices - 1
        ) // partition_vertices
        runtime_source_state_stride = selected_source_state_stride_bytes(
            parameters, destination_partitions
        )
        footprints = partition_layout_footprints(
            graph.records,
            update.records,
            graph.vertices,
            partition_vertices,
            range(graph.vertices),
            weighted_full_word=False,
        )
        if parameters.get("physical_address_map_id"):
            validate_partition_footprints(parameters, footprints)
            address_regions = validate_grasu_hbm_address_map(
                parameters,
                int(memory["channel_capacity_bytes"]),
                destination_partitions,
                graph.vertices,
                len(update.records),
                footprints,
            )
        env.update(
            {
                "GRASU_SST_MODE": "grasu_regraph_connected_components",
                "GRASU_SST_WORKLOAD": str(workload_path),
                "GRASU_SST_UPDATE_WORKLOAD": str(update_path),
                "GRASU_SST_OUTPUT": str(result_path),
                "GRASU_SST_DRAM_OUTPUT": str(dram_path),
                "GRASU_SST_CHANNELS": str(memory["channels"]),
                "GRASU_SST_ACTIVE_CHANNELS": ",".join(
                    str(value) for value in binding.instantiated_channels
                ),
                "GRASU_SST_CHANNEL_BYTES": str(memory["channel_capacity_bytes"]),
                "GRASU_SST_CORE_MHZ": str(core_mhz),
                "GRASU_SST_MAX_CYCLES": str(args.max_cycles),
                "GRASU_SST_MAX_ROUNDS": str(args.max_rounds),
                "GRASU_SST_CC_HARDWARE_FULL_RECOMPUTE": (
                    "1" if args.hardware_full_recompute else "0"
                ),
                "GRASU_SST_CACHE_SEGMENTS_PER_HALF": str(
                    parameters["grasu_cache_segments_per_cu"]
                ),
                "GRASU_SST_PARTITION_VERTICES": str(partition_vertices),
                "GRASU_SST_COMPUTE_PIPELINES": str(compute_pipelines),
                "GRASU_SST_SHARED_DOWNSTREAM": (
                    "1" if downstream_sharing == "shared" else "0"
                ),
                "GRASU_SST_SHARDED_RUNTIME_PLACEMENT": (
                    "1"
                    if parameters.get("grasu_sharded_runtime_placement", False)
                    else "0"
                ),
                "GRASU_SST_RUNTIME_CHANNEL_CAPACITY_BYTES": str(
                    parameters.get(
                        "grasu_runtime_channel_capacity_bytes",
                        memory["channel_capacity_bytes"],
                    )
                ),
                "GRASU_SST_SOURCE_BUFFER_VERTICES": str(source_buffer_vertices),
                "GRASU_SST_SOURCE_STATE_BUFFER_STRIDE": str(
                    runtime_source_state_stride
                ),
                "GRASU_SST_SOURCE_CACHE_REQUEST_FIFO_DEPTH": str(
                    parameters["regraph_source_cache_request_fifo_depth"]
                ),
                "GRASU_SST_SOURCE_CACHE_RESPONSE_FIFO_DEPTH": str(
                    parameters["regraph_source_cache_response_fifo_depth"]
                ),
                "GRASU_SST_EDGE_LANES": str(
                    parameters["regraph_map_reduce_lanes"]
                ),
                "GRASU_SST_GATHER_BANKS": str(
                    parameters["regraph_map_reduce_lanes"]
                ),
                "GRASU_SST_AXIS_FIFO_DEPTH": str(
                    parameters["regraph_pma_adapter_axis_fifo_depth"]
                ),
                "GRASU_SST_GATHER_BYPASS_DISTANCE": str(
                    parameters["regraph_gather_bypass_distance"]
                ),
                "GRASU_SST_GATHER_PIPELINE_LATENCY": str(
                    parameters["regraph_gather_pipeline_latency"]
                ),
                "GRASU_SST_SOURCE_STATE_CHANNEL": str(
                    parameters["regraph_source_state_channel"]
                ),
                "GRASU_SST_SOURCE_STATE_MIRROR_CHANNEL": str(
                    parameters["regraph_source_state_mirror_channel"]
                ),
                "GRASU_SST_APPLY_STATE_CHANNEL": str(
                    parameters["regraph_apply_state_channel"]
                ),
                "GRASU_SST_GATHER_MERGER_FIFO_DEPTH": str(
                    parameters["regraph_gather_merger_fifo_depth"]
                ),
                "GRASU_SST_MERGER_APPLY_FIFO_DEPTH": str(
                    parameters["regraph_merger_apply_fifo_depth"]
                ),
                "GRASU_SST_APPLY_WRAPPER_FIFO_DEPTH": str(
                    parameters["regraph_apply_wrapper_fifo_depth"]
                ),
                "GRASU_SST_MAX_PENDING_REQUESTS": str(
                    memory["max_outstanding_per_port"]
                ),
                "GRASU_SST_MAX_OUTSTANDING_BURSTS": str(
                    memory["max_outstanding_per_port"]
                ),
                "GRASU_SST_APPLY_REQUEST_WINDOW": str(
                    parameters["regraph_apply_request_window"]
                ),
                "GRASU_SST_APPLY_PIPELINE_LATENCY": str(
                    parameters["regraph_apply_pipeline_latency"]
                ),
                "GRASU_SST_APPLY_PIPELINE_CAPACITY": str(
                    parameters["regraph_apply_pipeline_capacity"]
                ),
                "GRASU_SST_HBM_WRAPPER_PIPELINE_LATENCY": str(
                    parameters["regraph_hbm_wrapper_pipeline_latency"]
                ),
                "GRASU_SST_HBM_WRAPPER_PIPELINE_CAPACITY": str(
                    parameters["regraph_hbm_wrapper_pipeline_capacity"]
                ),
            }
        )
        if address_regions is not None:
            env.update(grasu_hbm_address_environment(parameters, address_regions))
        sst_config = ROOT / "sst/grasu_regraph_vertical.py"

    if args.wrapper is None:
        sst_library = forced_sst_library_binding(args.sst, args.lib_dir)
        command = [
            str(args.sst.resolve()),
            sst_library["command_option"],
            str(sst_config),
        ]
    else:
        env.update(
            {
                "SPINE_IDLE_SST_INSTALL_PREFIX": str(
                    args.sst_install_prefix.resolve()
                ),
                "SPINE_IDLE_DRAMSIM3_SRC": str(args.dramsim3_src.resolve()),
                "SPINE_CYCLE_ELEMENT_DIR": str(args.lib_dir.resolve()),
            }
        )
        command = [str(args.wrapper.resolve()), str(sst_config)]
        sst_library = {
            "command_option": "wrapper_managed",
            "plugin_path": str(plugin),
            "plugin_sha256": sha256_file(plugin),
        }

    # The SST child reloads both slices from their file paths.  Keep only the
    # compact oracle result and update analysis while it runs; retaining these
    # three Python graph payloads duplicates the full graph in host memory.
    del graph, update, final_graph
    host_heap_trimmed = release_process_heap()
    start = time.monotonic()
    if not args.reuse_result:
        completed = subprocess.run(
            command,
            cwd=ROOT,
            env=env,
            check=False,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
        )
        log_path.write_text(completed.stdout, encoding="utf-8")
        if completed.returncode != 0:
            raise RuntimeError(
                f"SST CC run failed with rc={completed.returncode}; see {log_path}"
            )
    wall_seconds = time.monotonic() - start
    result = json.loads(result_path.read_text(encoding="utf-8"))
    dram = load_dram_stats(dram_path)
    checks = validate_result(
        result,
        architecture=args.architecture,
        expected_labels=oracle_labels,
        analysis=analysis,
        compute_pipelines=compute_pipelines,
        downstream_sharing=(
            downstream_sharing if args.architecture == "grasu" else "native"
        ),
        hardware_full_recompute=args.hardware_full_recompute,
    )
    checks["dram_request_ledger"] = (
        dram["channels"] == len(binding.instantiated_channels)
        and dram["reads"] + dram["writes"] == result.get("backend_requests")
    )
    failed = [name for name, passed in checks.items() if not passed]
    manifest = {
        "schema_version": 1,
        "architecture": args.architecture,
        "source_revision": _git_revision(),
        "profile": str(profile_path),
        "profile_id": profile["profile_id"],
        "profile_sha256": sha256_file(profile_path),
        "algorithm_capability": capability_record,
        "algorithm_contract": "weakly_connected_min_vertex_reciprocal_v1",
        "workload": str(workload_path),
        "workload_sha256": sha256_file(workload_path),
        "update_workload": str(update_path),
        "update_sha256": sha256_file(update_path),
        "sst_plugin": str(plugin),
        # The plugin path is mutable during parallel campaigns. Record the
        # hash captured before subprocess launch, which is the image SST loaded.
        "sst_plugin_sha256": sst_library["plugin_sha256"],
        "sst_library_binding": sst_library,
        "sst_memory_binding": binding.as_manifest(),
        "physical_hbm_address_regions": address_regions,
        "runtime_source_state_stride_bytes": runtime_source_state_stride,
        "core_mhz": core_mhz,
        "compute_pipelines": compute_pipelines,
        "downstream_sharing": (
            downstream_sharing if args.architecture == "grasu" else None
        ),
        "partition_vertices": partition_vertices,
        "logical_user_mutations": analysis.logical_user_mutations,
        "effective_mutations": analysis.effective_mutations,
        "physical_records": analysis.physical_records,
        "update_mode": expected_update_mode(
            analysis,
            hardware_full_recompute=args.hardware_full_recompute,
        ),
        "hardware_full_recompute": args.hardware_full_recompute,
        "host_oracle_storage": "graph_payload_released_before_sst_launch_v1",
        "host_heap_trimmed": host_heap_trimmed,
        "sst_host_wall_seconds": wall_seconds,
        "command": command,
        "dram": dram,
        "status": "PASS" if not failed else "FAIL",
        "checks": checks,
        "admitted": not failed,
    }
    (args.out_dir / "run_manifest.json").write_text(
        json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="ascii"
    )
    if failed:
        raise AssertionError(f"CC result failed admission checks: {', '.join(failed)}")
    print(
        f"PASS {args.architecture} CC: cycles={result['cycles']} "
        f"iterations={result['iterations']} components={result['components']} "
        f"K={manifest['compute_pipelines']} wall={wall_seconds:.3f}s"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
