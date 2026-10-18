"""Inspect actual exported interfaces and resources, without admitting routed timing."""

from pathlib import Path
import math
import shlex
import xml.etree.ElementTree as ET
from zipfile import ZipFile

from spine_cycle_sim.experiments.sharded_k4_stages.execution import identity
from ....search_pipeline.synthesis import unchanged
from ...resource_fit import account, platform_screen, resources, topology

PART = "xcu55c-fsvh2892-2L-e"
PART_RESOURCES = {"LUT": 1303680, "FF": 2607360, "BRAM_18K": 4032,
                  "URAM": 960, "DSP": 9024}


def device_screen(ledger, available):
    """Reject impossible estimates; passing does not reserve shell resources."""
    if available != PART_RESOURCES:
        raise ValueError("HLS available resources differ from the exact U55C part")
    return {"part_capacity": available,
            "oversubscribed_resources": [name for name, value in ledger["hls_totals"].items()
                                         if value > available[name]],
            "claim": "whole_device_HLS_estimate_screen_not_shell_free_fit_or_timing"}


def unique(nodes, key):
    result = {node[key]: node for node in nodes}
    if len(result) != len(nodes):
        raise ValueError("duplicate exported interface identity: " + key)
    return result


def definitions(options):
    tokens, result, index = shlex.split(options), {}, 0
    while index < len(tokens):
        token = tokens[index]
        if token in ("-D", "-U"):
            index += 1
            if index == len(tokens):
                raise ValueError("missing exported macro name")
            token += tokens[index]
        if token.startswith(("-DGRASU_", "-UGRASU_", "-DCACHE_BANK_", "-UCACHE_BANK_")):
            if token.startswith("-U"):
                raise ValueError("ambiguous exported macro undefinition")
            name, _, value = token[2:].partition("=")
            if name in result:
                raise ValueError("duplicate exported macro definition")
            result[name] = value or "1"
        index += 1
    return result


def exported(xo, kernel, argv):
    with ZipFile(xo) as archive:
        members = [name for name in archive.namelist() if name == kernel + "/kernel.xml"]
        if len(members) != 1:
            raise ValueError("one canonical exported kernel XML required")
        root = ET.fromstring(archive.read(members[0]))
    nodes = root.findall("kernel")
    if len(nodes) != 1 or nodes[0].get("name") != kernel:
        raise ValueError("exported top differs from compile kernel")
    node = nodes[0]
    macros = definitions(node.get("compileOptions", ""))
    if macros != definitions(shlex.join(argv)):
        raise ValueError("XO macros differ from declared compile command")
    ports = unique([dict(port.attrib) for port in node.findall("ports/port")], "name")
    args = unique([dict(arg.attrib) for arg in node.findall("args/arg")], "name")
    unique(list(args.values()), "id")
    for arg in args.values():
        if arg.get("port") not in ports:
            raise ValueError("exported argument references absent port")
    if kernel == "pma_to_regraph_adapter":
        row = args.get("row_offset")
        pma = args.get("pma0")
        if row is None or pma is None or row["port"] != pma["port"] or \
                int(ports[row["port"]]["dataWidth"]) != 512:
            raise ValueError("512-bit shared row/PMA master ABI required")
    return {"kernel": kernel, "control": node.get("hwControlProtocol"),
            "ports": ports, "args": args, "macros": macros}


def connectivity(contents):
    section, streams, memory = "", [], []
    for original in contents.splitlines():
        line = original.partition("#")[0].strip()
        if line.startswith("[") and line.endswith("]"):
            section = line[1:-1]
        elif line and section == "connectivity":
            key, equal, value = line.partition("=")
            if not equal:
                raise ValueError("malformed connectivity entry")
            key, value = key.strip(), value.strip()
            if key == "stream_connect":
                parts = value.split(":")
                if len(parts) not in (2, 3) or (len(parts) == 3 and int(parts[2]) <= 0):
                    raise ValueError("invalid stream endpoint/depth")
                streams.append(parts)
            elif key == "sp":
                endpoint, separator, bank = value.partition(":")
                if not separator or not bank:
                    raise ValueError("invalid memory mapping")
                memory.append((endpoint, bank))
    return streams, memory


def check_connections(contents, interfaces):
    kernels, placements = topology(contents)
    if set(kernels) != set(interfaces):
        raise ValueError("all and only declared kernel exports required")
    owners = {instance: interfaces[kernel] for kernel, instances in kernels.items() for instance in instances}

    def endpoint(value):
        instance, separator, argument = value.partition(".")
        if not separator or instance not in owners or argument not in owners[instance]["args"]:
            raise ValueError("unknown configured instance/argument: " + value)
        interface = owners[instance]
        arg = interface["args"][argument]
        return instance, arg, interface["ports"][arg["port"]]

    streams, memory = connectivity(contents)
    used, connections, mapped = set(), [], {}
    for source, sink, *depth in streams:
        width = None
        for value, mode in ((source, "write_only"), (sink, "read_only")):
            instance, arg, port = endpoint(value)
            identity = (instance, arg["port"])
            if identity in used or port.get("portType") != "stream" or port.get("mode") != mode:
                raise ValueError("stream reused or direction/type mismatch: " + value)
            current = int(port["dataWidth"])
            if current <= 0 or (width is not None and width != current):
                raise ValueError("stream data width mismatch")
            width = current
            used.add(identity)
        connections.append({"source": source, "sink": sink, "width_bits": width,
                            "fifo_depth": int(depth[0]) if depth else None})
    expected = {(instance, name) for instance, interface in owners.items()
                for name, port in interface["ports"].items() if port.get("portType") == "stream"}
    if used != expected:
        raise ValueError("unconnected exported stream ports")
    memory_endpoints = set()
    for value, bank in memory:
        instance, arg, port = endpoint(value)
        if value in memory_endpoints or port.get("portType") != "addressable" or port.get("mode") != "master":
            raise ValueError("duplicate or non-master memory mapping")
        memory_endpoints.add(value)
        identity = (instance, arg["port"])
        if identity in mapped and mapped[identity] != bank:
            raise ValueError("aliased master arguments mapped to different banks")
        mapped[identity] = bank
    masters = {(instance, name) for instance, interface in owners.items()
               for name, port in interface["ports"].items() if port.get("portType") == "addressable"
               and port.get("mode") == "master"}
    return {"kernels": kernels, "placements": placements, "streams": connections,
            "explicit_memory_masters": [{"instance": key[0], "port": key[1], "bank": bank}
                                        for key, bank in sorted(mapped.items())],
            "automatic_memory_masters": [{"instance": key[0], "port": key[1]}
                                         for key in sorted(masters - mapped.keys())]}


def inspect(config, compiles, physical, platform):
    pins = [identity(config), *[identity(Path(row["xo"])) for row in compiles]]
    contents = config.read_text()
    interfaces = {row["kernel"]: exported(Path(row["xo"]), row["kernel"], row["argv"]) for row in compiles}
    if len(interfaces) != len(compiles):
        raise ValueError("duplicate compiled kernel")
    checked = check_connections(contents, interfaces)
    estimates, reports = {}, []
    for row in compiles:
        argv = row["argv"]
        compile_config = Path(argv[argv.index("--config") + 1])
        pins.append(identity(compile_config))
        values = dict(line.split("=", 1) for line in compile_config.read_text().splitlines()
                      if "=" in line and not line.startswith("#"))
        kernel = row["kernel"]
        candidates = list(Path(values["temp_dir"]).rglob(kernel + "_csynth.xml"))
        if len(candidates) != 1:
            raise ValueError("one exact top-level csynth report required: " + kernel)
        report = candidates[0]
        pins.append(identity(report))
        root = ET.parse(report).getroot()
        clock = float(root.findtext("UserAssignments/TargetClockPeriod"))
        estimated = float(root.findtext("PerformanceEstimates/SummaryOfTimingAnalysis/EstimatedClockPeriod"))
        if root.findtext("UserAssignments/Part") != PART:
            raise ValueError("resource report target part changed")
        if not math.isfinite(clock) or abs(clock - 1000 / 150) > 0.01:
            raise ValueError("resource report requested clock changed")
        if not math.isfinite(estimated) or estimated <= 0:
            raise ValueError("resource report estimate must be finite and positive")
        estimates[kernel] = resources(report, kernel)
        available = {name: int(root.findtext("AreaEstimates/AvailableResources/" + name))
                     for name in PART_RESOURCES}
        if available != PART_RESOURCES:
            raise ValueError("HLS available resources differ from the exact U55C part")
        reports.append({"kernel": kernel, "path": str(report), "target_ns": clock,
                        "estimated_ns": estimated, "available_resources": available})
    ledger = account(checked["kernels"], checked["placements"], estimates, physical)
    ledger["whole_device_screen"] = device_screen(ledger, reports[0]["available_resources"])
    ledger["platform_storage_screen"] = platform_screen(ledger, physical, platform)
    conflict = any(row["uram_oversubscribed_slrs"] or row["total_uram_capacity_exceeded"]
                   for row in (ledger, ledger["platform_storage_screen"]))
    unchanged(pins)
    return {"status": "RESOURCE_ESTIMATE_CONFLICT_REQUIRES_IMPLEMENTATION_REVIEW" if
            ledger["whole_device_screen"]["oversubscribed_resources"] else
            "STORAGE_CONFLICT_REQUIRES_PLACEMENT_REVIEW" if conflict else
            "EXPORT_AND_STORAGE_SCREEN_PASS_NOT_RTL_OR_ROUTE_ADMISSION",
            "interfaces": interfaces, "connections": checked, "resource_ledger": ledger,
            "reports": reports, "pins": pins, "routed": False, "board_admitted": False,
            "rtl_admitted": False, "publication_match": False}
