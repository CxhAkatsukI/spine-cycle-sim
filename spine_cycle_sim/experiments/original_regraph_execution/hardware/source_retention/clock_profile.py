"""Explicit downclocked controls; nominal and HBM-only gates remain unchanged."""

from copy import deepcopy

from . import clocks
from .runtime import execute


NAMES = (("DATA", "DATA_CLK"), ("KERNEL", "KERNEL_CLK"), ("SYSTEM", "hbm_aclk"))


def validate(profile):
    if (len(profile) != 4 or any(type(v) is not int for v in profile)
            or not 100 <= profile[0] <= 150 or profile[0] % 5
            or profile[1] != 500 or not 300 <= profile[2] <= 450
            or profile[2] % 5 or profile[3] != 0):
        raise ValueError("explicit DATA/KERNEL/HBM/unused downclock profile required")
    return list(profile)


def retarget(payload, profile):
    target = dict(zip(NAMES, validate(profile)[:3]))
    copy = deepcopy(payload)
    topology = copy["clock_freq_topology"]
    rows = topology["m_clock_freq"]
    source = {(r["m_type"], r["m_name"]): int(r["m_freq_Mhz"]) for r in rows}
    if int(topology["m_count"]) != 3 or len(rows) != 3 or set(source) != set(target):
        raise ValueError("one exact three-clock U55C topology required")
    if any(not 0 < target[key] <= source[key] for key in target) or source[NAMES[1]] != 500:
        raise ValueError("clock-only control must never increase a source clock")
    for row in rows:
        row["m_freq_Mhz"] = str(target[row["m_type"], row["m_name"]])
    return copy


def check(evidence, profile):
    record = clocks.replay(evidence)
    if record["driver_reported_mhz"] != validate(profile):
        raise ValueError("driver clocks differ from the explicit matched profile")
    return record


def prepare(binary, expected, profile, output, name, fd, node, bdf, *, memory_gib=8):
    validate(profile)
    programmed = execute(["/opt/xilinx/xrt/bin/xrt-smi", "program", "-d", bdf, "-u", binary],
                         output, name + ".program", fd, node, bdf, memory_gib=memory_gib)
    before = clocks.capture(bdf, expected, output, name + ".before")
    check(before, profile)
    return {"program": programmed, "before": before}


def validate_after(preparation, after, profile):
    before_record, after_record = check(preparation["before"], profile), check(after, profile)
    if any(before_record[k] != after_record[k] for k in ("bdf", "uuid", "binary")):
        raise ValueError("board or image changed across the timed invocation")
