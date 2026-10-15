"""Check cache registers and both AXIS buses against the existing routed ABI."""

import xml.etree.ElementTree as ET

from ..search_binding.abi import NS, number, unique


def kernel(contents):
    nodes = ET.fromstring(contents).findall("kernel")
    if len(nodes) != 1 or nodes[0].get("name") != "process_cache":
        raise ValueError("expected one process_cache kernel")
    node = nodes[0]
    arguments = [{key: (number(arg.get(key)) if key in
        ("id", "addressQualifier", "offset", "size", "hostSize") else arg.get(key))
        for key in ("id", "name", "port", "addressQualifier", "offset", "size", "hostSize")}
        for arg in node.findall("args/arg")]
    if [row["id"] for row in arguments] != [0, 1, 2] or \
            [row["name"] for row in arguments] != ["pma_cache", "update_stream", "completion_token"]:
        raise ValueError("cache argument binding changed")
    ports = unique([{key: (number(port.get(key)) if key == "dataWidth" else port.get(key))
        for key in ("name", "portType", "mode", "dataWidth")}
        for port in node.findall("ports/port")], "name")
    return {"protocol": node.get("hwControlProtocol"), "arguments": arguments, "ports": ports}


def component(contents):
    root = ET.fromstring(contents)
    registers = unique([{"name": reg.findtext("s:name", namespaces=NS),
        "offset": number(reg.findtext("s:addressOffset", namespaces=NS)),
        "size": number(reg.findtext("s:size", namespaces=NS))}
        for reg in root.findall("s:memoryMaps/s:memoryMap/s:addressBlock/s:register", NS)], "name")
    ports = unique([{"name": port.findtext("s:name", namespaces=NS),
        "direction": port.findtext("s:wire/s:direction", namespaces=NS),
        "width": abs(number(port.findtext("s:wire/s:vector/s:left", "0", NS)) -
                     number(port.findtext("s:wire/s:vector/s:right", "0", NS))) + 1}
        for port in root.findall("s:model/s:ports/s:port", NS)], "name")
    interfaces = {}
    for name, direction, width in (("update_stream", "slave", 96), ("completion_token", "master", 32)):
        buses = [bus for bus in root.findall("s:busInterfaces/s:busInterface", NS)
                 if bus.findtext("s:name", namespaces=NS) == name]
        if len(buses) != 1 or buses[0].find("s:" + direction, NS) is None:
            raise ValueError("missing unique cache AXIS direction")
        mappings = []
        for mapping in buses[0].findall("s:portMaps/s:portMap", NS):
            logical = mapping.findtext("s:logicalPort/s:name", namespaces=NS)
            physical = mapping.findtext("s:physicalPort/s:name", namespaces=NS)
            mappings.append({"name": logical, "direction": ports[physical]["direction"],
                             "width": ports[physical]["width"]})
        signals = unique(mappings, "name")
        expected = {signal: {"name": signal, "width": bits,
            "direction": "out" if (direction == "master") != (signal == "TREADY") else "in"}
            for signal, bits in (("TDATA", width), ("TKEEP", width // 8), ("TSTRB", width // 8),
                                 ("TLAST", 1), ("TVALID", 1), ("TREADY", 1))}
        if signals != expected:
            raise ValueError("cache AXIS payload or sidebands changed")
        interfaces[name] = signals
    if not registers:
        raise ValueError("cache register map missing")
    return {"registers": registers, "axis": interfaces}


def compare(exported_kernel, exported_component, reference_kernel, reference_component):
    actual, reference = kernel(exported_kernel), kernel(reference_kernel)
    actual_ip, reference_ip = component(exported_component), component(reference_component)
    if actual != reference or actual["protocol"] != "ap_ctrl_chain" or actual_ip != reference_ip:
        raise ValueError("exported cache arguments, ports, control or register map differ")
    return {"kernel": actual, "component": actual_ip,
            "matches_routed_cache_abi": True, "board_execution_admitted": False}
