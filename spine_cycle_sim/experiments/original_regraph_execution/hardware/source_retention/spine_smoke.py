"""Qualify the later CC repair image without admitting a speedup result."""

import argparse
import json
import math
import os
from pathlib import Path
import re
import subprocess
import time

from spine_cycle_sim.experiments.evaluation_impact.fullgraph_readiness import board_memory
from spine_cycle_sim.experiments.sharded_k4_stages.link_runtime import run_link
from spine_cycle_sim.experiments.sharded_k4_stages.row_line.directory_tile.hardware import containment
from spine_cycle_sim.experiments.sharded_k4_stages.row_line.directory_tile.hardware.concurrent import Lease
from spine_cycle_sim.experiments.upstream_controls.execution import available_memory_bytes
from . import clocks
from .runtime import identity, lease, save


def validate(text, *, vertices=12, batches=11, physical_updates=None):
    records = []
    for line in text.splitlines():
        if line.startswith("CC_UPDATE_PASS "):
            values = dict(item.split("=", 1) for item in line.split()[1:])
            if any(values.get(key) != "0" for key in ("sample", "order", "hot", "full")):
                raise ValueError("expected one partial-repair sample in the cold layout")
            records.append(values)
    if ([int(row["batch"]) for row in records] != list(range(batches))
            or any(row.get("valid") != "1" or not math.isfinite(float(row["update_until_converged_ms"]))
                   or float(row["update_until_converged_ms"]) <= 0
                   or (physical_updates is not None and row.get("physical_records") != str(physical_updates))
                   for row in records)
            or text.splitlines().count(f"CC_REPAIR_PASS vertices={vertices} updates={batches} "
                                      "all_raw_labels_checked=1 all_raw_graphs_checked=1 "
                                      "all_round_work_checked=1") != 1
            or len(re.findall(r"^CC_BOOTSTRAP_PASS ", text, re.MULTILINE)) != 1):
        raise ValueError("CC workload did not complete every state/work oracle")
    return records


def resident_wall(text, *, vertices, physical_updates):
    rows = [line.split()[1:] for line in text.splitlines() if line.startswith("CC_RESIDENT_WALL ")]
    if len(rows) != 1:
        raise ValueError("one resident wall receipt required")
    values = dict(item.split("=", 1) for item in rows[0])
    expected = dict(sample="0", order="0", hot="0", full="0", batch="0",
                    vertices=str(vertices), physical_records=str(physical_updates))
    timers = ("host_pack_to_final_readback_ms", "batch_resident_to_final_readback_ms")
    if (len(rows[0]) != len(values) or set(values) != set(expected).union(timers)
            or any(values.get(key) != value for key, value in expected.items())):
        raise ValueError("resident wall receipt does not match the frozen workload")
    elapsed = {key: float(values[key]) for key in timers}
    if not 0 < elapsed[timers[1]] <= elapsed[timers[0]] < math.inf:
        raise ValueError("resident wall receipt has invalid timing windows")
    return elapsed


def run(args):
    wait = getattr(args, "admission_wait_seconds", 0)
    if type(wait) is not int or not 0 <= wait <= 21600:
        raise ValueError("admission wait must be bounded to six hours")
    input_manifest = getattr(args, "input_manifest", None)
    capture_wall = getattr(args, "resident_wall", False)
    if capture_wall and input_manifest is None:
        raise ValueError("resident wall requires the pinned single-batch input")
    output = args.output.resolve()
    output.mkdir(parents=True, exist_ok=False)
    group = containment.current()
    declared = board_memory.policy(24)
    board_memory.validate(containment.verify(group)["limits"], declared)
    board_memory.require_unthrottled((group / "memory.events").read_text())
    reservation = Lease(Path.home() / ".cache/spine-cycle-sim/compiler-reservations", group)
    pins = [identity(path) for path in (args.host, args.image,
                                      Path(str(args.image) + ".weighted-manifest"), Path(__file__))]
    workload = None
    if input_manifest is not None:
        pins.append(identity(input_manifest))
        workload = json.loads(input_manifest.read_text())
        for name in ("source", "graph", "update"):
            pin = workload[name]
            if identity(pin["path"]) != pin:
                raise ValueError(f"CC workload {name} pin mismatch")
            pins.append(pin)
    report = {"status": "PREPARING", "performance_admission": False, "pins": pins,
              "scope": "canonical 12-vertex CC fixture; one sample, 11 distinct batches; not a G+R comparison",
              "errors": [], "device": 0, "bdf": "0000:82:00.1"}
    if workload is not None:
        report.update(scope="frozen resident CC graph; one update batch; not a G+R comparison",
                      workload=workload, host_timer="batch upload through publication, excludes final label readback")
    if capture_wall:
        report["host_timer"] = "also records pack-start and batch-resident to one checked final label readback"
    save(output / "results.json", report)
    try:
        started = time.monotonic()
        report["admission_attempts"] = 0
        while True:
            if any(identity(pin["path"]) != pin for pin in pins):
                raise ValueError("CC image, host or runner changed before memory admission")
            board_memory.require_unthrottled((group / "memory.events").read_text())
            report["admission"] = reservation.sample(available_memory_bytes(), containment.other_builds(),
                                                     declared, commit=True)
            report["admission_attempts"] += 1
            report["admission_waited_seconds"] = time.monotonic() - started
            report["status"] = "MEMORY_ADMITTED" if report["admission"]["admitted"] else "WAITING_FOR_MEMORY_ADMISSION"
            save(output / "results.json", report)
            if report["admission"]["admitted"]:
                break
            if report["admission_waited_seconds"] >= wait:
                raise MemoryError("complete peer budgets plus the 24-GiB smoke and reserve do not fit")
            time.sleep(min(30, wait - report["admission_waited_seconds"]))
        with lease(0, report["bdf"]) as (node, fd):
            if subprocess.run(["fuser", str(node)], capture_output=True, timeout=10).returncode != 1:
                raise RuntimeError("Spine candidate board is not demonstrably idle")
            expected = clocks.image(args.image, output, "spine_cc")
            command = ["/usr/bin/taskset", "-c", "124,125", str(args.host), "--xclbin", str(args.image),
                       "--hot", "0", "--mode", "partial", "--samples", "1"]
            if workload is not None:
                command.extend(("--slice", workload["graph"]["path"], "--update", workload["update"]["path"]))
            environment = dict(os.environ, XILINX_XRT="/opt/xilinx/xrt", MALLOC_ARENA_MAX="2")
            # This native Spine host does not consume a lease fd; the parent holds it throughout.
            result = run_link(command, output, output / "spine_cc", timeout=240,
                              tree_memory_gib=24, reserve_gib=32, environment=environment)
            report["execution"] = result
            if (result["exit_code"] or result["stop_reason"] != "process_exit"
                    or result["cleanup_snapshot_error"]):
                raise RuntimeError("Spine CC smoke failed; raw logs retained")
            report["clock_evidence"] = clocks.capture(report["bdf"], expected, output, "spine_cc")
            clocks.replay(report["clock_evidence"])
            report["stdout"] = identity(output / "spine_cc.stdout.txt")
            report["stderr"] = identity(output / "spine_cc.stderr.txt")
            expected_work = {} if workload is None else dict(vertices=workload["vertices"], batches=1,
                                                             physical_updates=workload["updates"])
            stdout = Path(report["stdout"]["path"]).read_text()
            report["batches"] = validate(stdout, **expected_work)
            if capture_wall:
                report["resident_wall_ms"] = resident_wall(stdout, vertices=workload["vertices"],
                                                           physical_updates=workload["updates"])
            if any(identity(pin["path"]) != pin for pin in pins):
                raise ValueError("CC image, host or runner changed during the smoke")
            board_memory.require_unthrottled((group / "memory.events").read_text())
        label = "CANONICAL" if workload is None else "RESIDENT"
        report["status"] = f"{label}_CC_STATE_WORK_AND_CLOCK_PASS_NOT_PERFORMANCE_ADMISSION"
    except BaseException as error:
        report.update(status="FAILED_RETAINED")
        report["errors"].append(repr(error))
        raise
    finally:
        reservation.release()
        report["memory_peak_bytes"] = int((group / "memory.peak").read_text())
        report["memory_events"] = (group / "memory.events").read_text()
        save(output / "results.json", report)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("host", "image", "output"):
        parser.add_argument("--" + name, required=True, type=Path)
    parser.add_argument("--input-manifest", type=Path)
    parser.add_argument("--resident-wall", action="store_true")
    parser.add_argument("--admission-wait-seconds", type=int, default=0)
    run(parser.parse_args())
