"""Compare exported search registers and AXIS ports with the routed host ABI."""

import xml.etree.ElementTree as ET
from pathlib import PurePosixPath

NS = {"s": "http://www.spiritconsortium.org/XMLSchema/SPIRIT/1685-2009"}
NAMES = ("edges", *(f"binary_{i}" for i in range(4)),
         *(f"row_offset_{i}" for i in range(4)), "edge_size", "segment_head_stream_out")


def exported_members(archive):
    names = archive.namelist()
    components = [name for name in names if len(PurePosixPath(name).parts) == 3
                  and PurePosixPath(name).parts[0] == "ip_repo"
                  and PurePosixPath(name).name == "component.xml"]
    # Vivado also packages scratch .Xil/kernel.xml files; these are not the XO ABI.
    if names.count("bin_search/kernel.xml") != 1 or len(components) != 1:
        raise ValueError("missing or duplicate canonical exported ABI")
    return {"kernel.xml": "bin_search/kernel.xml", "component.xml": components[0]}


def number(value):
    if not isinstance(value, str):
        raise ValueError("missing ABI number")
    return int(value, 16) if value.lower().startswith("0x") else int(value)


def unique(rows, key):
    result = {row[key]: row for row in rows}
    if len(result) != len(rows):
        raise ValueError("duplicate ABI entry: " + key)
    return result


def kernel(contents):
    nodes = ET.fromstring(contents).findall("kernel")
    if len(nodes) != 1 or nodes[0].get("name") != "bin_search":
        raise ValueError("expected one bin_search kernel")
    node = nodes[0]
    arguments = [{key: (number(arg.get(key)) if key in
        ("id", "addressQualifier", "offset", "size", "hostSize") else arg.get(key))
        for key in ("id", "name", "port", "addressQualifier", "offset", "size", "hostSize")}
        for arg in node.findall("args/arg")]
    if [row["id"] for row in arguments] != list(range(11)) or \
            [row["name"] for row in arguments] != list(NAMES):
        raise ValueError("eleven-argument search binding changed")
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
    buses = [bus for bus in root.findall("s:busInterfaces/s:busInterface", NS)
             if bus.findtext("s:name", namespaces=NS) == "segment_head_stream_out"]
    if len(buses) != 1 or buses[0].find("s:master", NS) is None:
        raise ValueError("missing unique output AXIS master")
    signals = []
    for mapping in buses[0].findall("s:portMaps/s:portMap", NS):
        logical = mapping.findtext("s:logicalPort/s:name", namespaces=NS)
        physical = mapping.findtext("s:physicalPort/s:name", namespaces=NS)
        signals.append({"name": logical, "direction": ports[physical]["direction"],
                        "width": ports[physical]["width"]})
    signals = unique(signals, "name")
    expected = {name: {"name": name, "direction": "in" if name == "TREADY" else "out", "width": width}
                for name, width in (("TDATA", 96), ("TKEEP", 12), ("TSTRB", 12),
                                    ("TLAST", 1), ("TVALID", 1), ("TREADY", 1))}
    if signals != expected or not registers:
        raise ValueError("AXIS sidebands or register map changed")
    return {"registers": registers, "axis": signals}


def compare(exported_kernel, exported_component, reference_kernel, reference_component):
    actual, reference = kernel(exported_kernel), kernel(reference_kernel)
    if actual != reference or actual["protocol"] != "ap_ctrl_chain":
        raise ValueError("exported kernel arguments, address qualifiers, ports or control protocol differ")
    actual_ip, reference_ip = component(exported_component), component(reference_component)
    if actual_ip != reference_ip:
        raise ValueError("exported register map or AXIS interface differs")
    return {"kernel": actual, "component": actual_ip,
            "matches_routed_search_abi": True, "board_execution_admitted": False}
