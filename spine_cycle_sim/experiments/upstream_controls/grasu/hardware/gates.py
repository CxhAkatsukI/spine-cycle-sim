"""Inspect original interfaces, HLS target and routed metadata; never programs XRT."""

import json
import math
import xml.etree.ElementTree as ET
import zipfile

from spine_cycle_sim.experiments.sharded_k4_stages.execution import identity
from spine_cycle_sim.experiments.sharded_k4_stages.bitstream import SECTIONS, normalized_topology, parse_routed_timing
from . import configuration as config
from .topology import validate as validate_topology


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


def inspect_routed(metadata, reports):
    sections = {name: json.loads((metadata / (name + ".json")).read_text()) for name in SECTIONS.values()}
    topology = normalized_topology(sections)
    validate_topology(topology)
    paths = list(reports.glob("**/impl_1_hw_bb_locked_timing_summary_routed.rpt"))
    if len(paths) != 1:
        raise ValueError("one original G final routed timing report required")
    timing = parse_routed_timing(paths[0])
    if any(not math.isfinite(timing[key]) for key in ("wns_ns", "whs_ns", "wpws_ns")):
        raise ValueError("original G routed slacks must be finite")
    return {"status": "ORIGINAL_G_ROUTED_TOPOLOGY_TIMING_CHECKED_NOT_BOARD_ADMISSION",
            "topology": topology, "timing": timing,
            **dict.fromkeys(config.FLAGS, False)}
