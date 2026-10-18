"""Bounded physical-only refinement of a terminal algorithm routed checkpoint."""

import argparse
from pathlib import Path
import shutil
import sys
import time

from spine_cycle_sim.experiments.campaign_runtime import atomic_write_json
from spine_cycle_sim.experiments.sharded_k4_stages.execution import identity
from spine_cycle_sim.experiments.sharded_k4_stages.link_runtime import run_link
from spine_cycle_sim.experiments.sharded_k4_stages.row_line.directory_tile.hardware.concurrent import Lease
from spine_cycle_sim.experiments.sharded_k4_stages.row_line.directory_tile.hardware.containment import current, other_builds, verify
from spine_cycle_sim.experiments.upstream_controls.execution import available_memory_bytes
from ....continuous_board.execution.supervisor import service_state
from ....search_pipeline.synthesis import unchanged
from ..remote import environment
from . import analysis, inputs

POLICY = {"tree_memory_gib": 40, "reserve_gib": 32, "background_memory_gib": 8,
          "allow_bounded_builds": True}


def run(route, unit, invocation, output, environment_root, xilinx, platform, compatibility,
        *, producer_kind="algorithm"):
    output.mkdir(parents=True, exist_ok=False)
    report = {"status": "PREPARING_POSTROUTE_DIAGNOSTIC", "errors": [],
              "bitstream_generated": False, "board_admitted": False, "publication_match": False,
              "final_figures_admitted": False}
    save = lambda: atomic_write_json(output / "results.json", report)
    group, lease = None, None
    save()
    try:
        parent = inputs.admit(route, unit, invocation, producer_kind=producer_kind)
        group = current()
        report["containment"] = verify(group)
        if shutil.disk_usage(output).free < 80 * 1024**3:
            raise ValueError("80 GiB free disk required")
        for name in ("tmp", "user-data"):
            (output / name).mkdir()
        source = Path(__file__).with_name("refine.tcl")
        shutil.copyfile(source, output / "refine.tcl")
        effective, contract = environment.capture(environment_root, output, xilinx, platform, compatibility)
        atomic_write_json(output / "environment.json", contract)
        pins = parent["pins"] + contract["pins"] + [identity(source), identity(output / "refine.tcl"),
                                                   identity(output / "environment.json")]
        pins += [identity(Path(module.__file__)) for name, module in list(sys.modules.items())
                 if name.startswith("spine_cycle_sim.") and getattr(module, "__file__", None)]
        command = [contract["tools"]["vivado"]["invocation"], "-mode", "batch", "-source",
                   str(output / "refine.tcl"), "-tclargs", parent["checkpoint"], str(output)]
        manifest = {"parent": parent, "command": command, "pins": pins, "policy": POLICY,
                    "passes": list(analysis.PASSES), "timeout_seconds": 14400,
                    "scope": "physical_checkpoint_diagnostic_no_new_HLS_clock_or_bitstream"}
        atomic_write_json(output / "manifest.json", manifest)
        pins = pins + [identity(output / "manifest.json")]
        lease = Lease(Path.home() / ".cache/spine-cycle-sim/compiler-reservations", group)
        deadline = time.monotonic() + 86400
        while True:
            report["admission"] = lease.sample(available_memory_bytes(), other_builds(), POLICY, commit=True)
            report["status"] = "WAITING_FOR_COMPLETE_MEMORY_BUDGETS"
            save()
            if report["admission"]["admitted"]:
                break
            if time.monotonic() >= deadline:
                raise TimeoutError("postroute diagnostic admission timed out")
            time.sleep(10)
        unchanged(pins)
        if service_state(unit) != parent["service"]:
            raise ValueError("checkpoint producer invocation changed")
        report["status"] = "PHYSICAL_REFINEMENT_NOT_BITSTREAM_OR_BOARD_ADMISSION"
        save()
        report["step"] = run_link(command, output, output / "refine", timeout=14400,
                                  environment=effective, tree_memory_gib=40, reserve_gib=32)
        child = report["step"]
        if child["exit_code"] or child["stop_reason"] != "process_exit" or child["cleanup_snapshot_error"]:
            raise RuntimeError("checkpoint diagnostic failed; all partial reports retained")
        events = dict(line.split() for line in (group / "memory.events").read_text().splitlines())
        if any(events.get(key) != "0" for key in ("oom", "oom_kill", "oom_group_kill")):
            raise RuntimeError("checkpoint diagnostic has OOM events")
        unchanged(pins)
        report["analysis"] = analysis.inspect(output)
        report["status"] = "POSTROUTE_DIAGNOSTIC_COMPLETE_NOT_BITSTREAM_OR_BOARD_ADMISSION"
    except BaseException as error:
        report.update(status="FAILED_RETAINED", errors=[repr(error)])
        raise
    finally:
        if lease is not None:
            lease.release()
        if group is not None:
            report["memory_events_after"] = (group / "memory.events").read_text()
        save()
    return report


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("route", "output", "environment-root", "xilinx", "platform", "compatibility"):
        parser.add_argument("--" + name, required=True, type=Path)
    for name in ("unit", "invocation"):
        parser.add_argument("--" + name, required=True)
    parser.add_argument("--producer-kind", choices=inputs.PRODUCERS, default="algorithm")
    run(**vars(parser.parse_args()))
