"""Online execution-driven AXI to SST memHierarchy/DRAMSim3 smoke."""

from __future__ import annotations

import os
from pathlib import Path

import sst


ROOT = Path(__file__).resolve().parents[1]
channels = int(os.environ.get("SPINE_SST_CHANNELS", "1"))
channel_bytes = int(os.environ.get("SPINE_SST_CHANNEL_BYTES", str(1 << 30)))
requests = int(os.environ.get("SPINE_SST_REQUESTS", "256"))
request_bytes = int(os.environ.get("SPINE_SST_REQUEST_BYTES", "64"))
stride_bytes = int(os.environ.get("SPINE_SST_STRIDE_BYTES", "64"))
write_percent = int(os.environ.get("SPINE_SST_WRITE_PERCENT", "0"))
output = os.environ.get("SPINE_SST_OUTPUT", "sst_memory_probe.json")
dram_output = Path(os.environ.get("SPINE_SST_DRAM_OUTPUT", "/tmp/spine_cycle_dramsim3"))
dram_output.mkdir(parents=True, exist_ok=True)

probe = sst.Component("probe", "spine_cycle.OnlineMemoryProbe")
probe.addParams(
    {
        "mode": os.environ.get("SPINE_SST_MODE", "probe"),
        "output": output,
        "core_clock": "141MHz",
        "core_mhz": 141.0,
        "requests": requests,
        "request_bytes": request_bytes,
        "stride_bytes": stride_bytes,
        "channels": channels,
        "channel_capacity_bytes": channel_bytes,
        "write_percent": write_percent,
        "max_cycles": int(os.environ.get("SPINE_SST_MAX_CYCLES", "1000000")),
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
    link = sst.Link(f"probe_memory_{channel}")
    link.connect((interface, "lowlink", "1ns"), (memory, "highlink", "1ns"))
