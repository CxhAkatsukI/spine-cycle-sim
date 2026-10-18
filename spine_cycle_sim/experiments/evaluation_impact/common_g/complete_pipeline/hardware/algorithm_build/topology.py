"""Match routed XRT CU, memory and stream endpoints to fresh algorithm exports."""

from collections import defaultdict
import re

from spine_cycle_sim.experiments.sharded_k4_stages.bitstream import normalized_topology
from . import inspection, routing


def hbm_banks(value):
    match = re.fullmatch(r"HBM\[(\d+)(?::(\d+))?\]", value)
    if match is None:
        raise ValueError("explicit U55C HBM bank or range required")
    begin, end = int(match[1]), int(match[2] or match[1])
    if not 0 <= begin <= end < 32:
        raise ValueError("HBM bank range exceeds U55C")
    return {f"HBM[{index}]" for index in range(begin, end + 1)}


def check(sections, config, review):
    interfaces = review["interfaces"]
    connections = inspection.check_connections(config, interfaces)
    if review.get("status") != routing.PASS or connections != review["connections"] or \
            connections["automatic_memory_masters"]:
        raise ValueError("fresh algorithm export/configuration review differs")
    # XRT's stream IDs may change across links; compare their endpoint pairs,
    # not incidental dc_N names. Reject negative indices before normalization.
    ips = sections["ip"]["ip_layout"]["m_ip_data"]
    memory = sections["memory"]["mem_topology"]["m_mem_data"]
    for row in sections["connectivity"]["connectivity"]["m_connection"]:
        if not 0 <= int(row["m_ip_layout_index"]) < len(ips) or \
                not 0 <= int(row["mem_data_index"]) < len(memory) or int(row["arg_index"]) < 0:
            raise ValueError("invalid XRT connectivity index")
    normalized = normalized_topology(sections)
    data_clocks = [row for row in normalized["clock"] if row[0] == "DATA"]
    if data_clocks != [("DATA", "DATA_CLK", 150)]:
        raise ValueError("one 150-MHz accelerator data clock required")
    owners = {instance: (kernel, interfaces[kernel])
              for kernel, instances in connections["kernels"].items() for instance in instances}
    expected_cus = sorted((kernel + ":" + instance, interface["control"].upper())
                          for instance, (kernel, interface) in owners.items())
    if normalized["kernels"] != expected_cus:
        raise ValueError("routed CU identity/count/control differs from algorithm exports")
    masters = {(row["instance"], row["port"]): hbm_banks(row["bank"])
               for row in connections["explicit_memory_masters"]}

    def endpoint(value):
        instance, name = value.split(".")
        kernel, interface = owners[instance]
        return kernel + ":" + instance, int(interface["args"][name]["id"])

    expected_memory = set()
    for instance, (kernel, interface) in owners.items():
        for arg in interface["args"].values():
            for bank in masters.get((instance, arg["port"]), set()):
                expected_memory.add((kernel + ":" + instance, int(arg["id"]), bank))
    memory_by_tag = {row["m_tag"]: row for row in memory}
    if len(memory_by_tag) != len(memory):
        raise ValueError("duplicate XRT memory region")
    actual_memory, streams = [], defaultdict(list)
    for instance, argument, region in normalized["connections"]:
        entry = memory_by_tag[region]
        if entry["m_used"] != "1":
            raise ValueError("connected XRT memory/stream region marked unused")
        if entry["m_type"] == "MEM_STREAMING_CONNECTION":
            streams[region].append((instance, argument))
        else:
            actual_memory.append((instance, argument, region))
            if not region.startswith("HBM[") or int(entry["m_sizeKB"], 0) != 512 * 1024:
                raise ValueError("expected 512-MiB U55C HBM pseudochannels")
    if len(actual_memory) != len(set(actual_memory)) or set(actual_memory) != expected_memory:
        raise ValueError("routed argument/HBM bindings differ from actual master aliases")
    actual_streams = [tuple(sorted(pair)) for pair in streams.values()]
    expected_streams = [tuple(sorted((endpoint(row["source"]), endpoint(row["sink"]))))
                        for row in connections["streams"]]
    if any(len(pair) != 2 for pair in actual_streams) or sorted(actual_streams) != sorted(expected_streams):
        raise ValueError("routed AXIS endpoint pairs differ from declared algorithm graph")
    return {"topology": normalized, "memory_argument_bindings": len(actual_memory),
            "stream_pairs": len(actual_streams), "kernel_instances": len(expected_cus)}
