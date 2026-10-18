"""Independent original-G CU, bank and stream checks for a normalized xclbin."""

from collections import defaultdict

from . import configuration as config


def expected_connections():
    banks, streams = [], []

    def endpoint(value):
        instance, argument = value.split(".")
        kernel = instance.rsplit("_", 1)[0]
        return f"{kernel}:{instance}", config.argument_names(kernel).index(argument)

    for line in config.connectivity().splitlines():
        if line.startswith("sp="):
            port, bank = line.removeprefix("sp=").split(":")
            banks.append((*endpoint(port), bank))
        elif line.startswith("stream_connect="):
            source, target = line.removeprefix("stream_connect=").split(":")
            streams.append(frozenset((endpoint(source), endpoint(target))))
    return sorted(banks), streams


def validate(topology):
    expected_kernels = sorted((f"{name}:{name}_{index}", "AP_CTRL_CHAIN")
        for name, count in config.KERNELS.items() for index in range(1, count + 1))
    if sorted(topology["kernels"]) != expected_kernels:
        raise ValueError("original G requires exactly nine unchanged chain-control CUs")
    if sorted(topology["clock"]) != config.CLOCK_TOPOLOGY:
        raise ValueError("original G complete clock topology differs; automatic downclock is not admitted")
    memory = {row[0]: row for row in topology["memory"]}
    if len(memory) != len(topology["memory"]):
        raise ValueError("duplicate original G XRT memory tag")
    kernel_names = {name for name, _ in expected_kernels}
    observed_banks, observed_streams = [], defaultdict(list)
    for instance, argument, tag in topology["connections"]:
        if instance not in kernel_names or type(argument) is not int:
            raise ValueError("unknown original G CU or non-integer argument")
        arguments = config.argument_names(instance.split(":")[0])
        if not 0 <= argument < len(arguments):
            raise ValueError("original G argument index out of range")
        region = memory.get(tag)
        if region is None:
            raise ValueError("original G connection references missing memory")
        if region[1] == "MEM_STREAMING_CONNECTION":
            if int(region[2], 0) != 1 or int(region[3], 0) != 0:
                raise ValueError("original G AXIS must be enabled with no memory capacity")
            observed_streams[tag].append((instance, argument))
        else:
            observed_banks.append((instance, argument, tag))
    banks, streams = expected_connections()
    if sorted(observed_banks) != banks:
        raise ValueError("original G requires all 46 declared HBM argument bindings")
    if any(memory[tag][1] not in ("MEM_HBM", "MEM_DRAM") or int(memory[tag][2], 0) != 1 or
           int(memory[tag][3], 0) != 512 * 1024 for _, _, tag in banks):
        raise ValueError("original G connected HBM banks must be enabled 512 MiB")
    if any(len(ends) != 2 or len(set(ends)) != 2 for ends in observed_streams.values()):
        raise ValueError("original G AXIS requires exactly two distinct endpoints")
    pairs = [frozenset(ends) for ends in observed_streams.values()]
    if len(pairs) != len(streams) or set(pairs) != set(streams):
        raise ValueError("original G requires exactly eight declared AXIS pairs")
