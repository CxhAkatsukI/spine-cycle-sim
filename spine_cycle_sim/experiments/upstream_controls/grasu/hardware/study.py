"""Bounded remote original-G compilation/link; no automatic board admission."""

from pathlib import Path
import shutil
import socket
import sys
import time

from spine_cycle_sim.experiments.campaign_runtime import atomic_write_json
from spine_cycle_sim.experiments.sharded_k4_stages.execution import identity
from spine_cycle_sim.experiments.sharded_k4_stages.link_runtime import run_link
from spine_cycle_sim.experiments.sharded_k4_stages.empty_segment.route_environment import probe
from spine_cycle_sim.experiments.sharded_k4_stages.empty_segment.route_environment.contract import require_unchanged
from spine_cycle_sim.experiments.sharded_k4_stages.row_line.directory_tile.hardware.concurrent import Lease
from spine_cycle_sim.experiments.sharded_k4_stages.row_line.directory_tile.hardware.containment import current, other_builds, verify
from spine_cycle_sim.experiments.upstream_controls.execution import available_memory_bytes
from spine_cycle_sim.experiments.evaluation_impact.common_g.complete_pipeline.hardware.remote import environment
from spine_cycle_sim.experiments.evaluation_impact.common_g.search_pipeline.synthesis import unchanged
from . import configuration as config, gates, preparation


def run(packet, output, environment_root, xilinx, platform, compatibility):
    output.mkdir(parents=True, exist_ok=False)
    report = {"status": "PREPARING_ORIGINAL_G", "errors": [], "steps": [], "xos": [],
              "host": socket.gethostname(), "contract": preparation.contract(),
              **dict.fromkeys(config.FLAGS, False)}
    save = lambda: atomic_write_json(output / "results.json", report)
    group, lease = None, None
    save()
    try:
        packet_pins = preparation.verify(packet)
        group = current()
        report["containment"] = verify(group, memory_gib=config.POLICY["tree_memory_gib"])
        if shutil.disk_usage(output).free < 160 * 1024**3:
            raise ValueError("at least 160 GiB free build disk required")
        lease = Lease(Path.home() / ".cache/spine-cycle-sim/compiler-reservations", group)
        for name in ("tmp", "user-data", "xo"):
            (output / name).mkdir()
        effective, contract = environment.capture(environment_root, output, xilinx, platform, compatibility)
        atomic_write_json(output / "environment.json", contract)
        runners = {Path(module.__file__) for name, module in list(sys.modules.items())
                   if name.startswith("spine_cycle_sim.") and getattr(module, "__file__", None)}
        pins = [*packet_pins, *contract["pins"], *map(identity, sorted(runners)),
                identity(Path(sys.executable)), identity(output / "environment.json")]
        compilations, link = config.commands(contract["tools"]["v++"]["invocation"], platform, packet, output)
        atomic_write_json(output / "manifest.json", {"pins": pins, "compilations": compilations, "link": link,
            "compile_timeout_seconds": 7200, "link_timeout_seconds": 43200, "policy": config.POLICY,
            "source_modified": False, "interface_compacted": False, **dict.fromkeys(config.FLAGS, False)})
        pins.append(identity(output / "manifest.json"))
        report["manifest"] = pins[-1]
        deadline = time.monotonic() + 86400
        while True:
            unchanged(pins)
            report["admission"] = lease.sample(available_memory_bytes(), other_builds(), config.POLICY, commit=True)
            report["status"] = "WAITING_FOR_MEMORY_NOT_OTHER_TOOLS"
            save()
            if report["admission"]["admitted"]:
                break
            if time.monotonic() >= deadline:
                raise TimeoutError("complete finite budgets plus reserve do not fit")
            time.sleep(10)
        report["status"] = "ENVIRONMENT_PREFLIGHT"
        save()
        report["preflight"] = probe.run(output, effective, contract)
        pins.append(identity(output / "preflight/results.json"))

        def step(name, command, timeout):
            unchanged(pins)
            require_unchanged(contract, effective)
            report["status"] = name.upper() + "_RUNNING_NOT_BOARD_ADMISSION"
            save()
            print(report["status"], flush=True)
            child = run_link(command, output, output / name, timeout=timeout, environment=effective,
                             tree_memory_gib=40, reserve_gib=32)
            report["steps"].append({"id": name, **child})
            save()
            if child["exit_code"] or child["stop_reason"] != "process_exit" or child["cleanup_snapshot_error"]:
                raise RuntimeError("original G build failed or safely stopped: " + name)
            unchanged(pins)

        for name, command in compilations.items():
            step("compile_" + name, command, 7200)
            xo = gates.inspect_xo(output / "xo" / (name + ".hw.xo"), name)
            hls = gates.inspect_hls(output / "compile" / name, name)
            report["xos"].append({"abi": xo, "hls": hls})
            pins += [xo["xo"], hls["report"]]
            save()
        step("link", link, 43200)
        preparation.verify(packet)
        report.update(status="ORIGINAL_G_LINK_PASS_AWAITING_TIMING_CORRECTNESS_AND_BOARD",
                      xclbin=identity(output / "original_grasu.hw.xclbin"))
    except BaseException as error:
        report["status"] = "FAILED_RETAINED"
        report["errors"].append(repr(error))
        raise
    finally:
        if lease is not None:
            lease.release()
        if group is not None:
            report["memory_events_after"] = (group / "memory.events").read_text()
        save()
    return report
