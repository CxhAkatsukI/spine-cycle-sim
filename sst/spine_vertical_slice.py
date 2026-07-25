"""Stable-profile Spine vertical slice on online SST/DRAMSim3 HBM."""

from __future__ import annotations

import os
from pathlib import Path

import sst


ROOT = Path(__file__).resolve().parents[1]
channels = int(os.environ.get("SPINE_SST_CHANNELS", "32"))
channel_bytes = int(os.environ.get("SPINE_SST_CHANNEL_BYTES", str(512 << 20)))
workload = Path(
    os.environ.get(
        "SPINE_SST_WORKLOAD", str(ROOT / "tests" / "data" / "amazon_top1_exact.slice")
    )
).resolve()
preload_workload = os.environ.get("SPINE_SST_PRELOAD", "")
update_workload = os.environ.get("SPINE_SST_UPDATE_WORKLOAD", "")
hot_vertices = os.environ.get("SPINE_SST_HOT_VERTICES", "")
mode = os.environ.get("SPINE_SST_MODE", "spine_vertical")
core_mhz = float(os.environ.get("SPINE_SST_CORE_MHZ", "141.0"))
output = os.environ.get("SPINE_SST_OUTPUT", "sst_spine_vertical.json")
dram_output = Path(
    os.environ.get("SPINE_SST_DRAM_OUTPUT", "/tmp/spine_vertical_dramsim3")
)
dram_output.mkdir(parents=True, exist_ok=True)

probe = sst.Component("spine", "spine_cycle.OnlineMemoryProbe")
probe.addParams(
    {
        "mode": mode,
        "output": output,
        "workload": str(workload),
        "update_workload": update_workload,
        "preload_workload": preload_workload,
        "hot_vertices": hot_vertices,
        "source_vertex": int(os.environ.get("SPINE_SST_SOURCE", "2")),
        "core_clock": f"{core_mhz}MHz",
        "core_mhz": core_mhz,
        "channels": channels,
        "channel_capacity_bytes": channel_bytes,
        "max_cycles": int(os.environ.get("SPINE_SST_MAX_CYCLES", "1000000")),
        "max_rounds": int(os.environ.get("SPINE_SST_MAX_ROUNDS", "256")),
        "pagerank_iterations": int(
            os.environ.get("SPINE_SST_PAGERANK_ITERATIONS", "1")
        ),
        "pagerank_damping": float(
            os.environ.get("SPINE_SST_PAGERANK_DAMPING", "0.85")
        ),
        "pagerank_epsilon": float(
            os.environ.get("SPINE_SST_PAGERANK_EPSILON", "0.000001")
        ),
        "residual_max_iterations": int(
            os.environ.get("SPINE_SST_RESIDUAL_MAX_ITERATIONS", "256")
        ),
        "pagerank_source_latency": int(
            os.environ.get("SPINE_SST_PAGERANK_SOURCE_LATENCY", "3")
        ),
        "pagerank_source_ii": int(
            os.environ.get("SPINE_SST_PAGERANK_SOURCE_II", "1")
        ),
        "pagerank_source_capacity": int(
            os.environ.get("SPINE_SST_PAGERANK_SOURCE_CAPACITY", "4")
        ),
        "pagerank_edge_latency": int(
            os.environ.get("SPINE_SST_PAGERANK_EDGE_LATENCY", "1")
        ),
        "pagerank_edge_ii": int(
            os.environ.get("SPINE_SST_PAGERANK_EDGE_II", "1")
        ),
        "pagerank_edge_capacity": int(
            os.environ.get("SPINE_SST_PAGERANK_EDGE_CAPACITY", "4")
        ),
        "pagerank_reduce_latency": int(
            os.environ.get("SPINE_SST_PAGERANK_REDUCE_LATENCY", "2")
        ),
        "pagerank_reduce_ii": int(
            os.environ.get("SPINE_SST_PAGERANK_REDUCE_II", "1")
        ),
        "pagerank_reduce_capacity": int(
            os.environ.get("SPINE_SST_PAGERANK_REDUCE_CAPACITY", "8")
        ),
        "pagerank_apply_latency": int(
            os.environ.get("SPINE_SST_PAGERANK_APPLY_LATENCY", "3")
        ),
        "pagerank_apply_ii": int(
            os.environ.get("SPINE_SST_PAGERANK_APPLY_II", "1")
        ),
        "pagerank_apply_capacity": int(
            os.environ.get("SPINE_SST_PAGERANK_APPLY_CAPACITY", "8")
        ),
        "device_dirty_source_limit": int(
            os.environ.get("SPINE_SST_DEVICE_DIRTY_SOURCE_LIMIT", "4096")
        ),
        "range_task_active_gate": int(
            os.environ.get("SPINE_SST_RANGE_TASK_ACTIVE_GATE", "16384")
        ),
        "range_task_capacity": int(
            os.environ.get("SPINE_SST_RANGE_TASK_CAPACITY", "65536")
        ),
        "range_task_payload_budget": int(
            os.environ.get("SPINE_SST_RANGE_TASK_PAYLOAD_BUDGET", "1048576")
        ),
        "fallback_replay_threshold": int(
            os.environ.get("SPINE_SST_FALLBACK_REPLAY_THRESHOLD", "65536")
        ),
        "memory_request_window": int(
            os.environ.get("SPINE_SST_MEMORY_REQUEST_WINDOW", "1")
        ),
        "compute_memory_request_window": int(
            os.environ.get("SPINE_SST_COMPUTE_MEMORY_REQUEST_WINDOW", "7")
        ),
        "compute_writeonly_request_window": int(
            os.environ.get("SPINE_SST_COMPUTE_WRITEONLY_REQUEST_WINDOW", "4")
        ),
        "compute_tiny_bram_read_latency": int(
            os.environ.get("SPINE_SST_COMPUTE_TINY_BRAM_READ_LATENCY", "2")
        ),
        "compute_vs_uram_read_latency": int(
            os.environ.get("SPINE_SST_COMPUTE_VS_URAM_READ_LATENCY", "2")
        ),
        "compute_active_bram_read_latency": int(
            os.environ.get("SPINE_SST_COMPUTE_ACTIVE_BRAM_READ_LATENCY", "2")
        ),
        "compute_onchip_pipeline_capacity": int(
            os.environ.get("SPINE_SST_COMPUTE_ONCHIP_PIPELINE_CAPACITY", "4")
        ),
        "compute_vs_bypass_depth": int(
            os.environ.get("SPINE_SST_COMPUTE_VS_BYPASS_DEPTH", "4")
        ),
        "reader_edge_pipeline_depth": int(
            os.environ.get("SPINE_SST_READER_EDGE_PIPELINE_DEPTH", "32")
        ),
        "reader_edge_response_capacity": int(
            os.environ.get("SPINE_SST_READER_EDGE_RESPONSE_CAPACITY", "32")
        ),
        "maintenance_count_scan_ii": int(
            os.environ.get("SPINE_SST_MAINTENANCE_COUNT_SCAN_II", "1")
        ),
        "maintenance_count_scan_tail_cycles": int(
            os.environ.get("SPINE_SST_MAINTENANCE_COUNT_SCAN_TAIL_CYCLES", "19")
        ),
        "maintenance_l0_write_scan_ii": int(
            os.environ.get("SPINE_SST_MAINTENANCE_L0_WRITE_SCAN_II", "24")
        ),
        "maintenance_l0_write_scan_tail_cycles": int(
            os.environ.get(
                "SPINE_SST_MAINTENANCE_L0_WRITE_SCAN_TAIL_CYCLES", "42"
            )
        ),
        "maintenance_scan_response_capacity": int(
            os.environ.get(
                "SPINE_SST_MAINTENANCE_SCAN_RESPONSE_CAPACITY", "32"
            )
        ),
        "spine_axi_profile": os.environ.get(
            "SPINE_SST_AXI_PROFILE", "hls_split_9c08763"
        ),
    }
)

dram_config = ROOT / "configs" / "memory" / "HBM2_1ch_x128.ini"
for channel in range(channels):
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
    link = sst.Link(f"spine_memory_{channel}")
    link.connect((interface, "lowlink", "1ns"), (memory, "highlink", "1ns"))
