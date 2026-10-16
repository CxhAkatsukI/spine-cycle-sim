"""Independent XO ABI, HLS target, routed clock and timing gates; never programs a board."""

import json
import math
from pathlib import Path
import shlex
import xml.etree.ElementTree as ET
import zipfile

from spine_cycle_sim.experiments.sharded_k4_stages.bitstream import normalized_topology, parse_routed_timing, SECTIONS
from .. import artifact
from . import configuration as config


def inspect_xo(path: Path, name: str) -> dict:
    with zipfile.ZipFile(path) as archive:
        entries = [item for item in archive.namelist() if item.endswith("/kernel.xml")]
        # Big's replicated dataflow metadata exceeds 1 MiB with the pinned 2024.1 compiler.
        maximum_xml_bytes = (4 if name == "bigKernelScatterGather" else 1) * 1024**2
        if len(entries) != 1 or archive.getinfo(entries[0]).file_size > maximum_xml_bytes:
            raise ValueError("one bounded kernel XML required")
        kernel = ET.fromstring(archive.read(entries[0])).find("kernel")
    if (kernel is None or kernel.get("name") != name or
            kernel.get("hwControlProtocol") != config.control_protocol(name)):
        raise ValueError("author kernel name or task-control ABI differs")
    arguments = [dict(arg.attrib) for arg in kernel.findall("args/arg")]
    if ([arg["name"] for arg in arguments] != config.argument_names(name) or
            [int(arg["id"]) for arg in arguments] != list(range(len(arguments)))):
        raise ValueError("author kernel argument order differs from guarded host ABI")
    tokens = shlex.split(kernel.get("compileOptions", ""))
    definitions = {}
    for index, token in enumerate(tokens):
        value = tokens[index + 1] if token == "-D" and index + 1 < len(tokens) else token[2:] if token.startswith("-D") else ""
        key, _, flag = value.partition("=")
        if key in config.DEFINES:
            if key in definitions:
                raise ValueError("ambiguous author macro redefinition")
            definitions[key] = flag or "1"
        undefined = tokens[index + 1] if token == "-U" and index + 1 < len(tokens) else token[2:] if token.startswith("-U") else ""
        if undefined in config.DEFINES:
            raise ValueError("author macro undefinition is not admitted")
    if definitions != {key: str(value) for key, value in config.DEFINES.items()}:
        raise ValueError("XO configuration differs from fixed signed-PR author control")
    return {"xo": artifact.identity(path), "kernel": name, "arguments": arguments,
            "control": kernel.get("hwControlProtocol"), "defines": definitions,
            "ports": [dict(port.attrib) for port in kernel.findall("ports/port")]}


def inspect_hls(directory: Path, name: str) -> dict:
    reports = list(directory.glob("**/" + name + "_csynth.xml"))
    if len(reports) != 1:
        raise ValueError("one HLS synthesis XML per author kernel required")
    document = ET.parse(reports[0]).getroot()
    assignments = document.find("UserAssignments")
    period = float(assignments.findtext("TargetClockPeriod")) if assignments is not None else math.nan
    if (assignments is None or assignments.findtext("Part") != config.PART or
            not math.isfinite(period) or abs(period - 1000 / config.CLOCK_MHZ) > 0.01):
        raise ValueError("HLS part or requested clock differs from same-platform control")
    return {"report": artifact.identity(reports[0]), "part": config.PART,
            "target_clock_ns": float(assignments.findtext("TargetClockPeriod")),
            "resources": {item.tag: item.text for item in document.findall("AreaEstimates/Resources/*")}}


def inspect_routed(metadata: Path, reports: Path) -> dict:
    sections = {name: json.loads((metadata / (name + ".json")).read_text()) for name in SECTIONS.values()}
    topology = normalized_topology(sections)
    expected = sorted(f"{name}:{name}_{index}" for name, (_, count) in config.KERNELS.items()
                      for index in range(1, count + 1))
    if sorted(row[0] for row in topology["kernels"]) != expected:
        raise ValueError("implemented original R does not have the declared eighteen CUs")
    clocks = [row[2] for row in topology["clock"] if row[0] == "DATA"]
    if clocks != [config.CLOCK_MHZ]:
        raise ValueError("implemented DATA clock differs; automatic frequency reduction is not admitted")
    memory = {row[0]: row for row in topology["memory"]}
    expected_connections = [("kernelApply:kernelApply_1", 0, "HBM[30]")]
    for lane in range(14):
        wrapper = "kernelHBMWrapper:kernelHBMWrapper_1"
        expected_connections += [(wrapper, lane, f"HBM[{2 * lane + 1}]"),
                                 (wrapper, lane + 14, f"HBM[{2 * lane + 1}]")]
        name = "littleKernelScatterGather" if lane < 11 else "bigKernelScatterGather"
        index = lane + 1 if lane < 11 else lane - 10
        expected_connections.append((f"{name}:{name}_{index}", 0, f"HBM[{2 * lane}]"))
    if topology["connections"] != sorted(expected_connections):
        raise ValueError("implemented HBM bank/argument bindings differ from author topology")
    # XRT encodes several U55C HBM banks as MEM_DRAM; tags and the pinned platform select the banks.
    if any(memory[tag][1] not in ("MEM_HBM", "MEM_DRAM") or int(memory[tag][2], 0) != 1 or
           int(memory[tag][3], 0) != 512 * 1024 for _, _, tag in expected_connections):
        raise ValueError("connected HBM regions must be enabled 512-MiB banks")
    for name, protocol in topology["kernels"]:
        expected_control = config.control_protocol(name.split(":")[0]).upper()
        if protocol != expected_control:
            raise ValueError("implemented CU control protocol differs from author ABI")
    timing_files = list(reports.glob("**/impl_1_hw_bb_locked_timing_summary_routed.rpt"))
    if len(timing_files) != 1:
        raise ValueError("one final implemented timing summary required")
    timing = parse_routed_timing(timing_files[0])
    return {"topology": topology, "timing": timing,
            "status": "ORIGINAL_R_ROUTED_CLOCK_TOPOLOGY_TIMING_PASS_AWAITING_BOARD",
            "board_programmed": False, "hardware_timing_measured": False, "publication_match": False}
