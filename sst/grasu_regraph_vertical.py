"""Execution-driven GraSU + PMA-native ReGraph on SST/DRAMSim3."""

from __future__ import annotations

import os
from pathlib import Path

import sst


ROOT = Path(__file__).resolve().parents[1]
channels = int(os.environ.get("GRASU_SST_CHANNELS", "32"))
channel_bytes = int(os.environ.get("GRASU_SST_CHANNEL_BYTES", str(512 << 20)))
workload = Path(
    os.environ.get(
        "GRASU_SST_WORKLOAD",
        str(ROOT / "tests" / "data" / "grasu_regraph_unit_initial.slice"),
    )
).resolve()
update = Path(
    os.environ.get(
        "GRASU_SST_UPDATE_WORKLOAD",
        str(ROOT / "tests" / "data" / "grasu_regraph_unit_update.slice"),
    )
).resolve()
output = os.environ.get("GRASU_SST_OUTPUT", "sst_grasu_regraph.json")
dram_output = Path(
    os.environ.get("GRASU_SST_DRAM_OUTPUT", "/tmp/grasu_regraph_dramsim3")
)
dram_output.mkdir(parents=True, exist_ok=True)
core_mhz = float(os.environ.get("GRASU_SST_CORE_MHZ", "150"))

probe = sst.Component("grasu_regraph", "spine_cycle.OnlineMemoryProbe")
probe.addParams(
    {
        "mode": "grasu_regraph_sssp",
        "output": output,
        "workload": str(workload),
        "update_workload": str(update),
        "source_vertex": int(os.environ.get("GRASU_SST_SOURCE", "0")),
        "core_clock": f"{core_mhz:g}MHz",
        "core_mhz": core_mhz,
        "channels": channels,
        "channel_capacity_bytes": channel_bytes,
        "max_cycles": int(os.environ.get("GRASU_SST_MAX_CYCLES", "2000000")),
        "max_rounds": int(os.environ.get("GRASU_SST_MAX_ROUNDS", "256")),
        "grasu_cache_segments_per_half": int(
            os.environ.get("GRASU_SST_CACHE_SEGMENTS_PER_HALF", "131072")
        ),
        "grasu_partition_vertices": int(
            os.environ.get("GRASU_SST_PARTITION_VERTICES", "16")
        ),
        "grasu_source_buffer_vertices": int(
            os.environ.get("GRASU_SST_SOURCE_BUFFER_VERTICES", "4096")
        ),
        "grasu_edge_lanes": int(os.environ.get("GRASU_SST_EDGE_LANES", "4")),
        "grasu_gather_banks": int(
            os.environ.get("GRASU_SST_GATHER_BANKS", "4")
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
    link = sst.Link(f"grasu_regraph_memory_{channel}")
    link.connect((interface, "lowlink", "1ns"), (memory, "highlink", "1ns"))
