"""Compile the frozen public A4 CC control on seele without board access."""

import argparse
import json
from pathlib import Path
import shutil
import socket
import time

from spine_cycle_sim.experiments.campaign_runtime import atomic_write_json
from spine_cycle_sim.experiments.evaluation_impact.common_g.complete_pipeline.hardware.remote import (
    capsule, environment, timing,
)
from spine_cycle_sim.experiments.sharded_k4_stages.empty_segment.route_environment import probe
from spine_cycle_sim.experiments.sharded_k4_stages.empty_segment.route_environment.contract import require_unchanged
from spine_cycle_sim.experiments.sharded_k4_stages.link_runtime import run_link
from spine_cycle_sim.experiments.sharded_k4_stages.row_line.directory_tile.hardware import high_memory, memory_profiles
from spine_cycle_sim.experiments.sharded_k4_stages.row_line.directory_tile.hardware.containment import current, other_builds, verify
from spine_cycle_sim.experiments.upstream_controls.execution import available_memory_bytes
from .. import artifact
from . import configuration, execution, gates, portable_inputs as inputs, snapshot

STATUS = "REMOTE_A4_CC_LINK_PASS_AWAITING_LOCAL_REVIEW"


def run(root, output, xilinx, platform, compatibility, digest, *, timing_profile=None):
    packet = inputs.verify(root, platform, xilinx, digest)
    policy = memory_profiles.select(capsule.POLICY, memory_profiles.SEELE)
    memory_profiles.host(policy)
    output.mkdir(parents=True, exist_ok=False)
    group = current()
    path = output / "results.json"
    report = {"status": "PREPARING", "errors": [], "host": socket.gethostname(), "steps": [], "xos": [],
              "capsule": artifact.identity(root / "capsule.json"), "policy": policy,
              "memory_profile": memory_profiles.SEELE, "board_programmed": False}
    lease = high_memory.lease(Path.home() / ".cache/spine-cycle-sim/compiler-reservations", group, policy)

    def save():
        atomic_write_json(path, report)

    try:
        report["containment"] = verify(group, memory_gib=40)
        if shutil.disk_usage(output).free < 160 * 2**30:
            raise ValueError("at least 160 GiB free build disk required")
        for member in ("tmp", "user-data", "xo", "algorithm/udf"):
            (output / member).mkdir(parents=True)
        udf = "algorithm/udf/l2.h"
        shutil.copyfile(root / udf, output / udf)
        entries = snapshot.prepare_entries(root / "source", output, inputs.TOPOLOGY)
        # Entry wrappers contain one absolute author include. Verify that relocation is the only edit.
        preflight = Path(json.loads((root / "source-preflight.json").read_text())["source_snapshot"]["source"])
        for name in configuration.kernels(inputs.TOPOLOGY):
            wrapper = f"entries/{name}.cpp"
            expected = (root / wrapper).read_text().replace(f'#include "{preflight}/',
                                                            f'#include "{root / "source"}/')
            if (output / wrapper).read_text() != expected:
                raise ValueError("relocated author wrapper differs: " + wrapper)
        if (output / "entries/apply_interface.tcl").read_bytes() != (root / "entries/apply_interface.tcl").read_bytes():
            raise ValueError("Apply interface directive differs")
        effective, contract = environment.capture(root, output, xilinx, platform, compatibility)
        atomic_write_json(output / "environment.json", contract)
        compiler = Path(contract["tools"]["v++"]["invocation"])
        commands = inputs.commands(root / "source", output, compiler, platform, timing_profile=timing_profile)
        pins = [report["capsule"], *[artifact.identity(root / name) for name in packet["files"]],
                *[artifact.identity(xilinx / name) for name in inputs.VENDOR_FILES], *contract["pins"],
                *entries, artifact.identity(output / udf), artifact.identity(output / "environment.json"),
                *execution.runner_pins()]
        atomic_write_json(output / "manifest.json", {"pins": pins, "commands": commands, "clock_mhz": 150,
                          "algorithm": inputs.ALGORITHM, "configuration": inputs.TOPOLOGY,
                          "timing_profile": timing_profile})
        report["manifest"] = artifact.identity(output / "manifest.json")
        pins.append(report["manifest"])
        deadline = time.monotonic() + 86400
        while True:
            report["admission"] = lease.sample(available_memory_bytes(), other_builds(), policy, commit=True)
            report["status"] = "WAITING_FOR_MEMORY"
            save()
            if report["admission"]["admitted"]:
                break
            if time.monotonic() >= deadline:
                raise TimeoutError("complete peer budgets plus reserve do not fit")
            time.sleep(10)
        report["status"] = "ENVIRONMENT_PREFLIGHT"
        save()
        report["preflight"] = probe.run(output, effective, contract)
        pins.append(artifact.identity(output / "preflight/results.json"))

        def step(name, argv, timeout):
            snapshot.unchanged(pins)
            require_unchanged(contract, effective)
            report["status"] = name.upper() + "_RUNNING"
            save()
            child = run_link(argv, output, output / name, environment=effective, timeout=timeout,
                             tree_memory_gib=40, reserve_gib=policy["reserve_gib"])
            report["steps"].append({"id": name, **child})
            save()
            if child["exit_code"] or child["stop_reason"] != "process_exit" or child["cleanup_snapshot_error"]:
                raise RuntimeError("public A4 step failed or safely stopped: " + name)
            memory_profiles.route_evidence(report, policy, child)
            snapshot.unchanged(pins)

        for name, argv in commands["compilations"].items():
            step("compile_" + name, argv, 1800)
            abi = gates.inspect_xo(output / "xo" / (name + ".hw.xo"), name, inputs.TOPOLOGY,
                                   algorithm=inputs.ALGORITHM)
            hls = gates.inspect_hls(output / "compile" / name, name)
            report["xos"].append({"abi": abi, "hls": hls})
            pins += [abi["xo"], hls["report"]]
            save()
        step("route", commands["link"], 43200)
        binary = configuration.binary_name(inputs.TOPOLOGY, algorithm=inputs.ALGORITHM)
        report.update(status=STATUS, xclbin=artifact.identity(output / binary), pins=pins)
    except BaseException as error:
        report["status"] = "FAILED_RETAINED"
        report["errors"].append(repr(error))
        raise
    finally:
        lease.release()
        report["memory_events_after"] = (group / "memory.events").read_text()
        save()
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("root", "output", "xilinx", "platform", "compatibility"):
        parser.add_argument("--" + name, type=Path, required=True)
    parser.add_argument("--digest", required=True)
    parser.add_argument("--timing-profile", choices=(timing.PROFILE,))
    args = parser.parse_args()
    run(args.root.resolve(), args.output.resolve(), args.xilinx.resolve(), args.platform.resolve(),
        args.compatibility.resolve(), args.digest, timing_profile=args.timing_profile)


if __name__ == "__main__":
    main()
