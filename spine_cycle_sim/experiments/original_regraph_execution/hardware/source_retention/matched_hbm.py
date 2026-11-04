"""Opt-in equal-clock control for a vendor-derated U55C candidate.

Both images must already encode their qualified operating profiles.
Neither programming nor clock checks are timed. No runtime reclock is used.
"""

from pathlib import Path

from . import clocks
from .runtime import execute


PROGRAM = Path("/opt/xilinx/xrt/bin/xrt-smi")


def validate_profile(frequencies, target):
    if (type(target) is not int or not 300 <= target <= 445 or target % 5 != 0
            or list(frequencies) != [150, 500, target, 0]):
        raise ValueError(f"expected actual clock profile 150/500/{target}/0 MHz; got {frequencies}")


def _check(frequencies, target, nominal):
    if not nominal:
        validate_profile(frequencies, target)
    elif target != 450 or list(frequencies) != [150, 500, 450, 0]:
        raise ValueError(f"expected nominal clock profile 150/500/450/0 MHz; got {frequencies}")


def prepare(binary, expected, target, output, name, fd, node, bdf, *, nominal=False):
    _check([150, 500, target, 0], target, nominal)
    programmed = execute([PROGRAM, "program", "-d", bdf, "-u", binary],
                         output, name + ".program", fd, node, bdf)
    before = clocks.capture(bdf, expected, output, name + ".before")
    _check(clocks.replay(before)["driver_reported_mhz"], target, nominal)
    return {"program": programmed, "before": before}


def validate_after(preparation, after, target, *, nominal=False):
    before_record = clocks.replay(preparation["before"])
    after_record = clocks.replay(after)
    if (before_record["bdf"], before_record["uuid"], before_record["binary"]) != (
            after_record["bdf"], after_record["uuid"], after_record["binary"]):
        raise ValueError("board or image changed across the timed host invocation")
    _check(before_record["driver_reported_mhz"], target, nominal)
    _check(after_record["driver_reported_mhz"], target, nominal)
