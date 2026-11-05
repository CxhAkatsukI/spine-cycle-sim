"""Prepare an offline clock-only copy of the nominal public U55C control."""

import argparse
from copy import deepcopy
import json
from pathlib import Path
import subprocess

from . import clock_profile, clocks, matched_hbm
from .runtime import identity, save


TOOL = Path("/opt/xilinx/xrt/bin/xclbinutil")


def retarget(payload, target):
    matched_hbm.validate_profile([150, 500, target, 0], target)
    copy = deepcopy(payload)
    topology = copy["clock_freq_topology"]
    rows = topology["m_clock_freq"]
    profile = {(row["m_type"], row["m_name"]): int(row["m_freq_Mhz"]) for row in rows}
    if int(topology["m_count"]) != 3 or len(rows) != 3 or profile != {
        ("SYSTEM", "hbm_aclk"): 450, ("KERNEL", "KERNEL_CLK"): 500, ("DATA", "DATA_CLK"): 150,
    }:
        raise ValueError("expected the exact nominal U55C control topology")
    next(row for row in rows if row["m_type"] == "SYSTEM")["m_freq_Mhz"] = str(target)
    return copy


def run(source, verifier, target, output, *, profile=None):
    output.mkdir(exist_ok=False)
    original = clocks.image(source, output, "original")
    source_clock = output / "original-clock.json"
    target_clock = output / "requested-clock.json"
    actual_clock = output / "derived-clock.json"
    binary = output / "control.xclbin"
    receipt = {"status": "FAILED_RETAINED", "original": original, "verifier": identity(verifier),
               "xclbinutil": identity(TOOL), "requested_hbm_mhz": target, "commands": []}
    if profile is not None:
        receipt["explicit_clock_profile_mhz"] = clock_profile.validate(profile)

    def invoke(name, command):
        command = list(map(str, command))
        receipt["commands"].append(command)
        with (output / f"{name}.log").open("x") as log:
            subprocess.run(command, stdout=log, stderr=subprocess.STDOUT, check=True, timeout=60)

    try:
        invoke("dump-original", [TOOL, "--input", source, "--dump-section",
                                 f"CLOCK_FREQ_TOPOLOGY:JSON:{source_clock}"])
        payload = json.loads(source_clock.read_text())
        requested = retarget(payload, target) if profile is None else clock_profile.retarget(payload, profile)
        save(target_clock, requested)
        invoke("repackage", [TOOL, "--input", source, "--replace-section",
                             f"CLOCK_FREQ_TOPOLOGY:JSON:{target_clock}", "--output", binary])
        invoke("dump-derived", [TOOL, "--input", binary, "--dump-section",
                                f"CLOCK_FREQ_TOPOLOGY:JSON:{actual_clock}"])
        if json.loads(actual_clock.read_text()) != requested:
            raise ValueError("repackaged clock topology differs from the request")
        invoke("verify", [verifier, source, binary])
        receipt.update(status="OFFLINE_VERIFIED_NOT_BOARD_QUALIFIED",
                       clock_topology=identity(actual_clock), derived=clocks.image(binary, output, "derived"))
    finally:
        save(output / "package.json", receipt)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("source", "verifier", "output"):
        parser.add_argument("--" + name, type=Path, required=True)
    parser.add_argument("--hbm-mhz", type=int, required=True)
    args = parser.parse_args()
    run(args.source.resolve(), args.verifier.resolve(), args.hbm_mhz, args.output.resolve())
