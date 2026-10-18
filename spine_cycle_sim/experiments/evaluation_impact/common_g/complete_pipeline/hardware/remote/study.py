"""Run one remote production link inside a bounded, memory-admitted cgroup."""

import json
from pathlib import Path
import socket
import shutil
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
from ....search_pipeline.synthesis import unchanged
from . import capsule, environment, timing


def run(root, output, xilinx, platform, compatibility, *, timing_profile=None):
    packet, parent = capsule.verify(root)
    output.mkdir(parents=True, exist_ok=False)
    group = current()
    report = {"status": "PREPARING", "errors": [], "host": socket.gethostname(),
              "capsule": identity(root / "capsule.json"), "parent": packet["parent"],
              "policy": packet["policy"], **dict.fromkeys(capsule.FLAGS, False)}
    save = lambda: atomic_write_json(output / "execution.json", report)
    lease = Lease(Path.home() / ".cache/spine-cycle-sim/compiler-reservations", group)
    save()
    try:
        report["containment"] = verify(group, memory_gib=40)
        report["disk_free_bytes_before"] = shutil.disk_usage(output).free
        if report["disk_free_bytes_before"] < 160 * 1024**3:
            raise ValueError("at least 160 GiB free build disk required")
        for member in ("tmp", "user-data"):
            (output / member).mkdir()
        effective, contract = environment.capture(root, output, xilinx, platform, compatibility)
        atomic_write_json(output / "environment.json", contract)
        (output / "link.cfg").write_text(timing.configure(capsule.configuration(
            (root / "parent/link.cfg").read_text(), output, platform), timing_profile))
        argv = capsule.command(packet, parent, root, output, contract["tools"]["v++"]["invocation"])
        runners = sorted({Path(module.__file__) for name, module in sys.modules.copy().items()
            if name.startswith("spine_cycle_sim.experiments") and getattr(module, "__file__", None)})
        pins = [report["capsule"], *[identity(root / row["member"]) for row in packet["files"]],
                *contract["pins"], *map(identity, runners), identity(Path(sys.executable)),
                identity(output / "environment.json"), identity(output / "link.cfg")]
        atomic_write_json(output / "manifest.json", {"command": argv, "pins": pins,
            "relocation": report["capsule"], "parent": packet["parent"], "policy": packet["policy"],
            "clock_mhz": 150, "timing_profile": timing_profile, **dict.fromkeys(capsule.FLAGS, False)})
        report["manifest"] = identity(output / "manifest.json")
        pins.append(report["manifest"])
        deadline = time.monotonic() + 86400
        while True:
            unchanged(pins)
            report["admission"] = lease.sample(available_memory_bytes(), other_builds(), packet["policy"], commit=True)
            report["status"] = "WAITING_FOR_MEMORY_NOT_OTHER_TOOLS"
            save()
            if report["admission"]["admitted"]:
                break
            if time.monotonic() >= deadline:
                raise TimeoutError("complete peer budgets plus reserve do not fit")
            time.sleep(10)
        report["status"] = "ENVIRONMENT_PREFLIGHT"
        save()
        report["preflight"] = probe.run(output, effective, contract)
        pins.append(identity(output / "preflight/results.json"))
        unchanged(pins)
        require_unchanged(contract, effective)
        report["status"] = "ROUTING_NOT_BOARD_ADMISSION"
        save()
        report["route"] = run_link(argv, output, output / "route", environment=effective,
            timeout=packet["timeout_seconds"], tree_memory_gib=40, reserve_gib=32)
        unchanged(pins)
        child = report["route"]
        binary = output / "candidate.hw.xclbin"
        if child["exit_code"] or child["stop_reason"] != "process_exit" or child["cleanup_snapshot_error"] or \
                not binary.is_file():
            raise RuntimeError("remote link failed or safely stopped; logs retained")
        report.update(status="LINK_PASS_AWAITING_TIMING_AND_BOARD", xclbin=identity(binary))
    except BaseException as error:
        report["status"] = "FAILED_RETAINED"
        report["errors"].append(repr(error))
        raise
    finally:
        lease.release()
        report["memory_events_after"] = (group / "memory.events").read_text()
        save()
    return report
