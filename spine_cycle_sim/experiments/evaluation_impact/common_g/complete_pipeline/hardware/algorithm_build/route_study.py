"""Bounded experimental link; no RTL, timing, board or publication admission."""

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
from ....search_pipeline.synthesis import unchanged
from ..remote import environment
from . import routing

POLICY = {"tree_memory_gib": 40, "reserve_gib": 32, "background_memory_gib": 8,
          "allow_bounded_builds": True}


def run(compilation, storage, output, xilinx, platform, compatibility, shim):
    compilation, storage, output, xilinx, platform, compatibility, shim = (
        path.resolve() for path in (compilation, storage, output, xilinx, platform, compatibility, shim))
    output.mkdir(parents=True, exist_ok=False)
    group = current()
    report = {"status": "PREPARING_EXPERIMENTAL_LINK", "errors": [], "host": socket.gethostname(),
              "policy": POLICY, "rtl_admitted": False, "board_admitted": False, "publication_match": False}
    save = lambda: atomic_write_json(output / "execution.json", report)
    lease = Lease(Path.home() / ".cache/spine-cycle-sim/compiler-reservations", group)
    save()
    try:
        report["containment"] = verify(group, memory_gib=40)
        report["disk_free_before_bytes"] = shutil.disk_usage(output).free
        if report["disk_free_before_bytes"] < 160 * 1024**3:
            raise ValueError("at least 160 GiB free route disk required")
        for name in ("tmp", "user-data"):
            (output / name).mkdir()
        effective, contract = environment.capture(shim, output, xilinx, platform, compatibility)
        atomic_write_json(output / "environment.json", contract)
        manifest = routing.prepare(compilation, storage, output, platform, contract["tools"]["v++"]["invocation"])
        report.update(algorithm=manifest["algorithm"], integration_revision=manifest["integration_revision"])
        runners = sorted({Path(module.__file__) for name, module in sys.modules.copy().items()
            if name.startswith("spine_cycle_sim.experiments") and getattr(module, "__file__", None)})
        pins = manifest["pins"]
        pins.extend([*contract["pins"], *map(identity, runners), identity(Path(sys.executable)),
                     identity(output / "environment.json")])
        atomic_write_json(output / "manifest.json", {**manifest, "policy": POLICY, "timeout_seconds": 43200})
        report["manifest"] = identity(output / "manifest.json")
        pins.append(report["manifest"])
        deadline = time.monotonic() + 86400
        while True:
            unchanged(pins)
            report["admission"] = lease.sample(available_memory_bytes(), other_builds(), POLICY, commit=True)
            report["status"] = "WAITING_FOR_MEMORY_NOT_OTHER_TOOLS"
            save()
            if report["admission"]["admitted"]:
                break
            if time.monotonic() >= deadline:
                raise TimeoutError("full finite route budgets plus reserve do not fit")
            time.sleep(10)
        report["status"] = "ENVIRONMENT_PREFLIGHT"
        save()
        report["preflight"] = probe.run(output, effective, contract)
        pins.append(identity(output / "preflight/results.json"))
        unchanged(pins)
        require_unchanged(contract, effective)
        report["status"] = "ROUTING_EXPERIMENT_NOT_RTL_OR_BOARD_ADMISSION"
        save()
        child = run_link(manifest["command"], output, output / "route", environment=effective,
                         timeout=43200, tree_memory_gib=40, reserve_gib=32)
        report["route"] = child
        unchanged(pins)
        binary = output / "candidate.hw.xclbin"
        if child["exit_code"] or child["stop_reason"] != "process_exit" or \
                child["cleanup_snapshot_error"] or not binary.is_file():
            raise RuntimeError("experimental link failed or safely stopped; logs retained")
        report.update(status="LINK_PASS_UNVERIFIED_RTL_AWAITING_TIMING_AND_BOARD", xclbin=identity(binary))
    except BaseException as error:
        report["status"] = "FAILED_RETAINED"
        report["errors"].append(repr(error))
        raise
    finally:
        lease.release()
        report["memory_events_after"] = (group / "memory.events").read_text()
        save()
    return report
