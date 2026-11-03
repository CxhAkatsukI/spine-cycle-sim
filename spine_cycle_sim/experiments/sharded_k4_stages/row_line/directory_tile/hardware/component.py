"""Compile one generated hardware component with source pins and finite memory."""

import argparse
import csv
from pathlib import Path
import shlex
import subprocess
import sys
import time

from spine_cycle_sim.experiments.campaign_runtime import atomic_write_json
from spine_cycle_sim.experiments.sharded_k4_stages.execution import identity
from spine_cycle_sim.experiments.sharded_k4_stages.link_runtime import run_link
from spine_cycle_sim.experiments.upstream_controls.execution import available_memory_bytes
from .concurrent import Lease
from .containment import GIB, current, other_builds, verify


def environment(packet):
    lines = (packet / "compile_commands.sh").read_text().splitlines()
    header = "\n".join(line for line in lines if not line.startswith("v++ "))
    result = subprocess.check_output(["bash", "-c", header + "\nenv -0"], timeout=60)
    return dict(item.decode().split("=", 1) for item in result.split(b"\0") if item)


def command(packet, kernel):
    lines = (packet / "compile_commands.sh").read_text().splitlines()
    commands = [shlex.split(line) for line in lines if line.startswith("v++ ")]
    selected = [argv for argv in commands if
                Path(argv[argv.index("-o") + 1]).name == kernel + ".hw.xo"]
    if len(selected) != 1:
        raise ValueError("exactly one generated component command required")
    argv = selected[0]
    if (argv[argv.index("--target") + 1] != "hw" or "--compile" not in argv
            or "--link" in argv):
        raise ValueError("only a hardware component compile is admitted")
    binary = Path(argv[argv.index("-o") + 1])
    if binary.parent != packet / "build" or binary.exists():
        raise ValueError("fresh component output inside packet/build required")
    return argv, binary, environment(packet)


def pins(packet):
    paths = {packet / "compile_commands.sh", packet / "inputs.tsv", packet / "manifest.env"}
    paths.update(p for p in (packet / "config").rglob("*") if p.is_file())
    with (packet / "inputs.tsv").open() as stream:
        for row in csv.DictReader(stream, delimiter="\t"):
            if row["status"] == "present":
                path = Path(row["path"])
                record = identity(path)
                if record["sha256"] != row["sha256"]:
                    raise ValueError("generated source pin changed: " + str(path))
                paths.add(path)
    return [identity(path) for path in sorted(paths)]


def runner_pins():
    paths = {Path(module.__file__) for name, module in sys.modules.copy().items()
             if name.startswith("spine_cycle_sim.experiments") and getattr(module, "__file__", None)}
    return [identity(path) for path in sorted(paths)]


def unchanged(records):
    if any(identity(Path(row["path"])) != row for row in records):
        raise ValueError("pinned build input changed during compilation")


def execute(output, argv, effective, records, *, kind, binary=None, timeout=7200, admission_wait=0):
    if type(admission_wait) is not int or not 0 <= admission_wait <= 21600:
        raise ValueError("memory admission wait must be between zero and six hours")
    output.mkdir(parents=True, exist_ok=False)
    report = {"status": "PREPARING", "kind": kind, "board_tested": False,
              "policy": {"tree_memory_gib": 40, "reserve_gib": 32,
                         "background_memory_gib": 8, "allow_bounded_builds": True}}
    group = current()
    lease = Lease(Path.home() / ".cache/spine-cycle-sim/compiler-reservations", group)
    try:
        report["containment"] = verify(group)
        if kind == "COMPONENT":
            budget, remainder = divmod(int(report["containment"]["limits"]["memory.max"]), GIB)
            if not budget or remainder:
                raise ValueError("component cgroup requires a whole-GiB hard limit")
            report["policy"]["tree_memory_gib"] = budget
        records = records + runner_pins()
        deadline = time.monotonic() + admission_wait
        while True:
            report["admission"] = lease.sample(available_memory_bytes(), other_builds(),
                                                report["policy"], commit=True)
            if report["admission"]["admitted"]:
                break
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise RuntimeError("complete finite compiler budget plus reserve does not fit")
            report["status"] = "WAITING_FOR_COMPILER_MEMORY"
            atomic_write_json(output / "execution.json", report)
            time.sleep(min(15, remaining))
        unchanged(records)
        atomic_write_json(output / "manifest.json", {"command": argv, "pins": records})
        report["status"] = "RUNNING_" + kind
        atomic_write_json(output / "execution.json", report)
        result = run_link(argv, output, output / "job", environment=effective,
                          timeout=timeout, tree_memory_gib=report["policy"]["tree_memory_gib"], reserve_gib=40)
        report["resources"] = result
        unchanged(records)
        if (result["exit_code"] or result["stop_reason"] != "process_exit"
                or result["cleanup_snapshot_error"] or (binary and not binary.is_file())):
            raise RuntimeError("hardware job failed; raw logs retained")
        if kind == "RANDOM_STALL_RTL":
            if "PMA_RANDOM_STALL_RTL_OUTPUT_CHECK_PASS" not in (output / "job.stdout.txt").read_text():
                raise RuntimeError("finite RTL did not complete all output comparisons")
            report.update(status="FINITE_RANDOM_STALL_RTL_PASS_NOT_BOARD")
        elif kind == "LINK":
            report.update(status="LINK_PASS_AWAITING_TIMING_AND_BOARD", xclbin=identity(binary))
        else:
            report.update(status="COMPONENT_XO_PASS_NOT_ROUTED", xo=identity(binary))
    except BaseException as error:
        report.update(status="FAILED_RETAINED", error=repr(error))
        raise
    finally:
        lease.release()
        report["memory_events_after"] = (group / "memory.events").read_text()
        atomic_write_json(output / "execution.json", report)
    return report


def run(packet, kernel, output):
    argv, binary, effective = command(packet, kernel)
    return execute(output, argv, effective, pins(packet), kind="COMPONENT", binary=binary)


def rtl(packet, integration, output, mode):
    effective = environment(packet)
    effective.update(PMA_COSIM_OUT=str(output), PMA_COSIM_MODE=mode,
                     PMA_COSIM_SHARED="1", HLS_INCLUDE="/data/yxx/tools/xilinx/Vitis_HLS/2024.1/include")
    sources = [*sorted((integration / "kernels/pma_prefetch_compact").glob("*.*")),
               *[integration / "tests" / name for name in (
                   "pma_prefetch_compact_cosim.tcl", "pma_prefetch_compact_cosim_tb.cpp",
                   "repair_cosim_axi_ids.tcl")]]
    argv = ["vitis_hls", "-f", str(integration / "tests/pma_prefetch_compact_cosim.tcl")]
    return execute(output, argv, effective, pins(packet) + list(map(identity, sources)),
                   kind="RANDOM_STALL_RTL")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--packet", required=True, type=Path)
    parser.add_argument("--kernel", default="pma_to_regraph_adapter")
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--rtl-mode", choices=("weighted", "destination", "unit"))
    parser.add_argument("--integration", type=Path)
    args = parser.parse_args()
    if args.rtl_mode:
        if args.integration is None:
            parser.error("--integration is required with --rtl-mode")
        print(rtl(args.packet.resolve(), args.integration.resolve(), args.output.resolve(), args.rtl_mode))
    else:
        print(run(args.packet.resolve(), args.kernel, args.output.resolve()))
