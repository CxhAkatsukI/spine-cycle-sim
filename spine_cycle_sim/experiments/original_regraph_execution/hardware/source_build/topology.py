"""Check HBM bindings and AXIS endpoint pairs as distinct XRT connections."""

from collections import defaultdict

from . import configuration as config


def memory_bindings(configuration):
    little, big = config.counts(configuration)
    total = little + big
    result = [("kernelApply:kernelApply_1", 0, "HBM[30]")]
    for lane in range(total):
        result += [("kernelHBMWrapper:kernelHBMWrapper_1", lane + offset,
                    f"HBM[{2 * lane + 1}]") for offset in (0, total)]
        name = "littleKernelScatterGather" if lane < little else "bigKernelScatterGather"
        index = lane + 1 if lane < little else lane - little + 1
        result.append((f"{name}:{name}_{index}", 0, f"HBM[{2 * lane}]"))
    return sorted(result)


def stream_pairs(configuration):
    little, big = config.counts(configuration)
    wrapper = "kernelHBMWrapper:kernelHBMWrapper_1"
    apply = "kernelApply:kernelApply_1"
    pairs = [frozenset(((apply, "prop_write_burst_stm"), (wrapper, "prop_write_burst_stm")))]
    for prefix, title, kernel, request, count in (
            ("l", "Little", "little", "ppb", little),
            ("b", "Big", "big", "cacheline", big)):
        if not count:
            continue
        merger = f"kernel{title}GSMerger:kernel{title}GSMerger_1"
        pairs.append(frozenset(((merger, prefix + "_write_burst_stm"),
                                (apply, prefix + "_merged_prop_stm"))))
        for lane in range(1, count + 1):
            gather = f"{kernel}KernelScatterGather:{kernel}KernelScatterGather_{lane}"
            for direction in ("request", "response"):
                name = f"{prefix}_{request}_{direction}_stm"
                pairs.append(frozenset(((gather, name), (wrapper, f"{name}_{lane}"))))
            pairs.append(frozenset(((gather, prefix + "_tmp_prop_stm"),
                                    (merger, f"{prefix}_tmp_prop_stm_{lane}"))))
    return pairs


def validate(topology, configuration):
    memory = {row[0]: row for row in topology["memory"]}
    if len(memory) != len(topology["memory"]):
        raise ValueError("duplicate XRT memory tag")
    hbm, streams = [], defaultdict(list)
    for instance, argument, tag in topology["connections"]:
        row = memory.get(tag)
        if row is None:
            raise ValueError("connection references missing XRT memory region")
        if row[1] != "MEM_STREAMING_CONNECTION":
            hbm.append((instance, argument, tag))
            continue
        if int(row[2], 0) != 1 or int(row[3], 0) != 0:
            raise ValueError("AXIS region must be enabled and have no memory capacity")
        names = config.argument_names(instance.split(":")[0], configuration)
        if not 0 <= argument < len(names):
            raise ValueError("AXIS argument index out of range")
        streams[tag].append((instance, names[argument]))
    expected = memory_bindings(configuration)
    if sorted(hbm) != expected:
        raise ValueError("implemented HBM bank/argument bindings differ from author topology")
    if any(memory[tag][1] not in ("MEM_HBM", "MEM_DRAM") or int(memory[tag][2], 0) != 1 or
           int(memory[tag][3], 0) != 512 * 1024 for _, _, tag in expected):
        raise ValueError("connected HBM regions must be enabled 512-MiB banks")
    if any(len(endpoints) != 2 or len(set(endpoints)) != 2 for endpoints in streams.values()):
        raise ValueError("each AXIS connection requires two distinct endpoints")
    pairs = [frozenset(endpoints) for endpoints in streams.values()]
    wanted = stream_pairs(configuration)
    if len(pairs) != len(wanted) or set(pairs) != set(wanted):
        raise ValueError("implemented AXIS endpoint pairs differ from author topology")
