"""Execution-driven GraSU + PMA-native ReGraph on SST/DRAMSim3."""

from __future__ import annotations

import os
from pathlib import Path

import sst


ROOT = Path(__file__).resolve().parents[1]
mode = os.environ.get("GRASU_SST_MODE", "grasu_regraph_sssp")
channels = int(os.environ.get("GRASU_SST_CHANNELS", "32"))
active_channel_text = os.environ.get("GRASU_SST_ACTIVE_CHANNELS", "").strip()
if active_channel_text:
    try:
        active_channels = tuple(int(value) for value in active_channel_text.split(","))
    except ValueError as exc:
        raise ValueError(
            "GRASU_SST_ACTIVE_CHANNELS must be a comma-separated integer list"
        ) from exc
    if (
        not active_channels
        or len(set(active_channels)) != len(active_channels)
        or any(channel < 0 or channel >= channels for channel in active_channels)
    ):
        raise ValueError(
            "GRASU_SST_ACTIVE_CHANNELS must contain unique in-range channels"
        )
else:
    active_channels = tuple(range(channels))
channel_bytes = int(os.environ.get("GRASU_SST_CHANNEL_BYTES", str(512 << 20)))
workload = Path(
    os.environ.get(
        "GRASU_SST_WORKLOAD",
        str(ROOT / "tests" / "data" / "grasu_regraph_unit_initial.slice"),
    )
).resolve()
update_text = os.environ.get(
    "GRASU_SST_UPDATE_WORKLOAD",
    str(ROOT / "tests" / "data" / "grasu_regraph_unit_update.slice"),
)
update = Path(update_text).resolve() if update_text else None
output = os.environ.get("GRASU_SST_OUTPUT", "sst_grasu_regraph.json")
dram_output = Path(
    os.environ.get("GRASU_SST_DRAM_OUTPUT", "/tmp/grasu_regraph_dramsim3")
)
dram_output.mkdir(parents=True, exist_ok=True)
memory_backend = os.environ.get(
    "GRASU_SST_MEMORY_BACKEND", "sst_memHierarchy_dramsim3"
)
core_mhz = float(os.environ.get("GRASU_SST_CORE_MHZ", "150"))

probe = sst.Component("grasu_regraph", "spine_cycle.OnlineMemoryProbe")
probe.addParams(
    {
        "mode": mode,
        "output": output,
        "progress_path": os.environ.get("SPINE_CAMPAIGN_PROGRESS_PATH", ""),
        "progress_interval_cycles": int(
            os.environ.get("SPINE_CAMPAIGN_PROGRESS_INTERVAL_CYCLES", "50000000")
        ),
        "memory_backend": memory_backend,
        "direct_dram_config": os.environ.get(
            "CANDIDATE10_SST_DRAM_CONFIG",
            str(ROOT / "configs" / "memory" / "HBM2_1ch_x128.ini"),
        ),
        "direct_dram_output": str(dram_output),
        "workload": str(workload),
        "update_workload": str(update) if update is not None else "",
        "source_vertex": int(os.environ.get("GRASU_SST_SOURCE", "0")),
        "core_clock": f"{core_mhz:g}MHz",
        "core_mhz": core_mhz,
        "channels": channels,
        "active_memory_channels": ",".join(
            str(channel) for channel in active_channels
        ),
        "channel_capacity_bytes": channel_bytes,
        "hbm_address_mapping": os.environ.get(
            "GRASU_SST_HBM_ADDRESS_MAPPING", "identity"
        ),
        "hbm_address_mapping_table": os.environ.get(
            "GRASU_SST_HBM_ADDRESS_MAPPING_TABLE", ""
        ),
        "hbm_interleave_first_channel": int(
            os.environ.get("GRASU_SST_HBM_INTERLEAVE_FIRST_CHANNEL", "0")
        ),
        "hbm_interleave_channels": int(
            os.environ.get("GRASU_SST_HBM_INTERLEAVE_CHANNELS", "0")
        ),
        "hbm_interleave_bytes": int(
            os.environ.get("GRASU_SST_HBM_INTERLEAVE_BYTES", "64")
        ),
        "max_cycles": int(os.environ.get("GRASU_SST_MAX_CYCLES", "2000000")),
        "max_rounds": int(os.environ.get("GRASU_SST_MAX_ROUNDS", "256")),
        "cc_hardware_full_recompute": int(
            os.environ.get("GRASU_SST_CC_HARDWARE_FULL_RECOMPUTE", "0")
        ),
        "grasu_native_supersteps": int(
            os.environ.get("GRASU_SST_NATIVE_SUPERSTEPS", "2")
        ),
        "pagerank_iterations": int(
            os.environ.get("GRASU_SST_PAGERANK_ITERATIONS", "3")
        ),
        "pagerank_damping": float(
            os.environ.get("GRASU_SST_PAGERANK_DAMPING", "0.85")
        ),
        "pagerank_epsilon": float(
            os.environ.get("GRASU_SST_PAGERANK_EPSILON", "0.000001")
        ),
        "residual_contract": os.environ.get(
            "GRASU_SST_RESIDUAL_CONTRACT", "generic_dangling_l1_cold"
        ),
        "residual_max_iterations": int(
            os.environ.get("GRASU_SST_RESIDUAL_MAX_ITERATIONS", "256")
        ),
        "grasu_cache_segments_per_half": int(
            os.environ.get("GRASU_SST_CACHE_SEGMENTS_PER_HALF", "131072")
        ),
        "grasu_partition_vertices": int(
            os.environ.get("GRASU_SST_PARTITION_VERTICES", "16")
        ),
        "grasu_compute_pipelines": int(
            os.environ.get("GRASU_SST_COMPUTE_PIPELINES", "1")
        ),
        "grasu_shared_downstream": int(
            os.environ.get("GRASU_SST_SHARED_DOWNSTREAM", "0")
        ),
        "grasu_sharded_runtime_placement": int(
            os.environ.get("GRASU_SST_SHARDED_RUNTIME_PLACEMENT", "0")
        ),
        "grasu_runtime_channel_capacity_bytes": int(
            os.environ.get(
                "GRASU_SST_RUNTIME_CHANNEL_CAPACITY_BYTES", "536870912"
            )
        ),
        "grasu_source_buffer_vertices": int(
            os.environ.get("GRASU_SST_SOURCE_BUFFER_VERTICES", "4096")
        ),
        "grasu_source_cache_request_fifo_depth": int(
            os.environ.get("GRASU_SST_SOURCE_CACHE_REQUEST_FIFO_DEPTH", "8")
        ),
        "grasu_source_cache_response_fifo_depth": int(
            os.environ.get("GRASU_SST_SOURCE_CACHE_RESPONSE_FIFO_DEPTH", "8")
        ),
        "grasu_edge_array_fifo_depth": int(
            os.environ.get("GRASU_SST_EDGE_ARRAY_FIFO_DEPTH", "8")
        ),
        "grasu_edge_lanes": int(os.environ.get("GRASU_SST_EDGE_LANES", "4")),
        "grasu_gather_banks": int(
            os.environ.get("GRASU_SST_GATHER_BANKS", "4")
        ),
        "grasu_gather_bypass_distance": int(
            os.environ.get("GRASU_SST_GATHER_BYPASS_DISTANCE", "6")
        ),
        "grasu_gather_pipeline_latency": int(
            os.environ.get("GRASU_SST_GATHER_PIPELINE_LATENCY", "9")
        ),
        "grasu_source_state_channel": int(
            os.environ.get("GRASU_SST_SOURCE_STATE_CHANNEL", "1")
        ),
        "grasu_source_state_mirror_channel": int(
            os.environ.get("GRASU_SST_SOURCE_STATE_MIRROR_CHANNEL", "3")
        ),
        "grasu_apply_state_channel": int(
            os.environ.get("GRASU_SST_APPLY_STATE_CHANNEL", "30")
        ),
        "grasu_gather_merger_fifo_depth": int(
            os.environ.get("GRASU_SST_GATHER_MERGER_FIFO_DEPTH", "16")
        ),
        "grasu_merger_apply_fifo_depth": int(
            os.environ.get("GRASU_SST_MERGER_APPLY_FIFO_DEPTH", "16")
        ),
        "grasu_apply_wrapper_fifo_depth": int(
            os.environ.get("GRASU_SST_APPLY_WRAPPER_FIFO_DEPTH", "16")
        ),
        "grasu_axis_fifo_depth": int(
            os.environ.get("GRASU_SST_AXIS_FIFO_DEPTH", "16")
        ),
        "grasu_reader_buffer_batches": int(
            os.environ.get("GRASU_SST_READER_BUFFER_BATCHES", "32")
        ),
        "grasu_max_pending_requests": int(
            os.environ.get("GRASU_SST_MAX_PENDING_REQUESTS", "32")
        ),
        "grasu_max_outstanding_bursts": int(
            os.environ.get("GRASU_SST_MAX_OUTSTANDING_BURSTS", "32")
        ),
        "grasu_apply_request_window": int(
            os.environ.get("GRASU_SST_APPLY_REQUEST_WINDOW", "32")
        ),
        "grasu_apply_pipeline_latency": int(
            os.environ.get("GRASU_SST_APPLY_PIPELINE_LATENCY", "100")
        ),
        "grasu_apply_pipeline_capacity": int(
            os.environ.get("GRASU_SST_APPLY_PIPELINE_CAPACITY", "100")
        ),
        "grasu_hbm_wrapper_pipeline_latency": int(
            os.environ.get("GRASU_SST_HBM_WRAPPER_PIPELINE_LATENCY", "71")
        ),
        "grasu_hbm_wrapper_pipeline_capacity": int(
            os.environ.get("GRASU_SST_HBM_WRAPPER_PIPELINE_CAPACITY", "71")
        ),
        "grasu_pagerank_source_map_latency": int(
            os.environ.get("GRASU_SST_PAGERANK_SOURCE_MAP_LATENCY", "1")
        ),
        "grasu_degree_channel": int(
            os.environ.get("GRASU_SST_DEGREE_CHANNEL", "30")
        ),
        "grasu_degree_fifo_depth": int(
            os.environ.get("GRASU_SST_DEGREE_FIFO_DEPTH", "16")
        ),
        "grasu_degree_reorder_entries": int(
            os.environ.get("GRASU_SST_DEGREE_REORDER_ENTRIES", "4096")
        ),
        "grasu_update_base": int(
            os.environ.get("GRASU_SST_UPDATE_BASE", "0")
        ),
        "grasu_binary_base": int(
            os.environ.get("GRASU_SST_BINARY_BASE", str(0x20000000))
        ),
        "grasu_row_offset_base": int(
            os.environ.get("GRASU_SST_ROW_OFFSET_BASE", str(0x10000000))
        ),
        "grasu_pma_base": int(
            os.environ.get("GRASU_SST_PMA_BASE", str(0x30000000))
        ),
        "grasu_vertex_state_base": int(
            os.environ.get("GRASU_SST_VERTEX_STATE_BASE", str(0x40000000))
        ),
        "grasu_source_state_base": int(
            os.environ.get("GRASU_SST_SOURCE_STATE_BASE", str(0x50000000))
        ),
        "grasu_source_state_buffer_stride": int(
            os.environ.get("GRASU_SST_SOURCE_STATE_BUFFER_STRIDE", str(1 << 20))
        ),
        "grasu_degree_base": int(
            os.environ.get("GRASU_SST_DEGREE_BASE", str(0x41000000))
        ),
        "grasu_edge_array_base": int(
            os.environ.get("GRASU_SST_EDGE_ARRAY_BASE", str(0x60000000))
        ),
        "grasu_edge_array_channel": int(
            os.environ.get("GRASU_SST_EDGE_ARRAY_CHANNEL", "0")
        ),
        "grasu_compactor_completion_tokens": int(
            os.environ.get("GRASU_SST_COMPACTOR_COMPLETION_TOKENS", "4")
        ),
        "grasu_compactor_lane_pipeline_latency": int(
            os.environ.get("GRASU_SST_COMPACTOR_LANE_PIPELINE_LATENCY", "72")
        ),
        "grasu_partition_address_stride": int(
            os.environ.get("GRASU_SST_PARTITION_ADDRESS_STRIDE", str(1 << 32))
        ),
        "grasu_packed_partition_addresses": int(
            os.environ.get("GRASU_SST_PACKED_PARTITION_ADDRESSES", "0")
        ),
        "grasu_partition_address_arena_base": int(
            os.environ.get(
                "GRASU_SST_PARTITION_ADDRESS_ARENA_BASE", str(16 << 20)
            )
        ),
        "grasu_partition_address_alignment": int(
            os.environ.get("GRASU_SST_PARTITION_ADDRESS_ALIGNMENT", "4096")
        ),
    }
)

dram_config = Path(
    os.environ.get(
        "CANDIDATE10_SST_DRAM_CONFIG",
        str(ROOT / "configs" / "memory" / "HBM2_1ch_x128.ini"),
    )
).resolve()
if not dram_config.is_file():
    raise ValueError(f"CANDIDATE10_SST_DRAM_CONFIG is not a file: {dram_config}")
for channel in active_channels if memory_backend == "sst_memHierarchy_dramsim3" else ():
    interface = probe.setSubComponent(
        "memory", "memHierarchy.standardInterface", channel
    )
    memory = sst.Component(f"memory{channel}", "memHierarchy.MemController")
    memory.addParams(
        {
            "clock": "1GHz",
            "addr_range_start": 0,
            "addr_range_end": channel_bytes - 1,
        }
    )
    backend = memory.setSubComponent("backend", "memHierarchy.dramsim3")
    channel_output = dram_output / f"channel{channel}"
    channel_output.mkdir(parents=True, exist_ok=True)
    backend.addParams(
        {
            "mem_size": f"{channel_bytes}B",
            "config_ini": str(dram_config),
            "output_dir": str(channel_output),
            "verbose": 0,
        }
    )
    link = sst.Link(f"grasu_regraph_memory_{channel}")
    link.connect((interface, "lowlink", "1ns"), (memory, "highlink", "1ns"))
