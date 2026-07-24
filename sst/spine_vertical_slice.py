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
hot_vertices = os.environ.get("SPINE_SST_HOT_VERTICES", "")
mode = os.environ.get("SPINE_SST_MODE", "spine_vertical")
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
        "preload_workload": preload_workload,
        "hot_vertices": hot_vertices,
        "source_vertex": int(os.environ.get("SPINE_SST_SOURCE", "2")),
        "core_clock": "141MHz",
        "core_mhz": 141.0,
        "channels": channels,
        "channel_capacity_bytes": channel_bytes,
        "max_cycles": int(os.environ.get("SPINE_SST_MAX_CYCLES", "1000000")),
        "max_rounds": int(os.environ.get("SPINE_SST_MAX_ROUNDS", "256")),
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
