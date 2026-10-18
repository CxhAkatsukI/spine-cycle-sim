"""Inspect original exported interfaces and HLS target; no routed-clock claim."""

import math
import xml.etree.ElementTree as ET
import zipfile

from spine_cycle_sim.experiments.sharded_k4_stages.execution import identity
from . import configuration as config


def inspect_xo(path, name):
    with zipfile.ZipFile(path) as archive:
        entries = [item for item in archive.infolist() if item.filename == name + "/kernel.xml"]
        if len(entries) != 1 or entries[0].file_size > 4 * 1024**2:
            raise ValueError("one bounded canonical original G kernel XML required")
        kernel = ET.fromstring(archive.read(entries[0])).find("kernel")
    if kernel is None or kernel.get("name") != name:
        raise ValueError("wrong original G kernel name")
    args = [dict(item.attrib) for item in kernel.findall("args/arg")]
    if ([row["name"] for row in args] != config.argument_names(name) or
            [int(row["id"]) for row in args] != list(range(len(args)))):
        raise ValueError("original G argument ABI differs")
    ports = [dict(item.attrib) for item in kernel.findall("ports/port")]
    masters = [row for row in ports if row.get("mode") == "master" and row.get("portType") == "addressable"]
    if len(masters) != {"bin_search": 9, "dispatch": 0, "process_cache": 1, "process_ddr": 4}[name]:
        raise ValueError("original G memory interfaces were compacted or changed")
    streams = [row for row in ports if row.get("portType") == "stream"]
    if (kernel.get("hwControlProtocol") != "ap_ctrl_chain" or
            len(streams) != (8 if name == "dispatch" else 1) or
            any(row.get("dataWidth") != "96" for row in streams)):
        raise ValueError("original G control or 96-bit stream ABI differs")
    return {"xo": identity(path), "kernel": name, "arguments": args, "ports": ports,
            "control": kernel.get("hwControlProtocol"), "memory_interfaces": len(masters)}


def inspect_hls(directory, name):
    files = list(directory.glob("**/" + name + "_csynth.xml"))
    if len(files) != 1:
        raise ValueError("one original G synthesis report required")
    tree = ET.parse(files[0]).getroot()
    period = float(tree.findtext("UserAssignments/TargetClockPeriod", "nan"))
    if (tree.findtext("UserAssignments/Part") != config.PART or not math.isfinite(period) or
            abs(period - 1000 / config.CLOCK_MHZ) > 0.01):
        raise ValueError("original G HLS part/target differs")
    return {"report": identity(files[0]), "target_clock_ns": period,
            "estimated_clock_ns": tree.findtext("PerformanceEstimates/SummaryOfTimingAnalysis/EstimatedClockPeriod"),
            "resources": {item.tag: item.text for item in tree.findall("AreaEstimates/Resources/*")}}
