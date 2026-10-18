"""Test a freshly exported adapter; synthetic AXI cycles are not FPGA timing."""

import json
from pathlib import Path
import shutil
import socket
import sys
import time

from spine_cycle_sim.experiments.campaign_runtime import atomic_write_json
from spine_cycle_sim.experiments.sharded_k4_stages.adapter_axi.analysis import parse_trace
from spine_cycle_sim.experiments.sharded_k4_stages.adapter_axi.study import BENCH, extract_rtl
from spine_cycle_sim.experiments.sharded_k4_stages.execution import identity
from spine_cycle_sim.experiments.sharded_k4_stages.link_runtime import run_link
from spine_cycle_sim.experiments.sharded_k4_stages.empty_segment.route_environment import probe
from spine_cycle_sim.experiments.sharded_k4_stages.empty_segment.route_environment.contract import require_unchanged
from spine_cycle_sim.experiments.sharded_k4_stages.row_line.directory_tile.validation import ALL_TRIALS
from spine_cycle_sim.experiments.sharded_k4_stages.row_line.directory_tile.hardware.concurrent import Lease
from spine_cycle_sim.experiments.sharded_k4_stages.row_line.directory_tile.hardware.containment import current, other_builds, verify
from spine_cycle_sim.experiments.upstream_controls.execution import available_memory_bytes
from ....search_pipeline.synthesis import unchanged
from ..remote import environment
from . import review

ROOT = Path(__file__).resolve().parents[7]
BANK_BENCH = "cpp/tests/routed_regraph/bank_stream_axi_tb.sv"
TRIALS = ALL_TRIALS + [(1023, 1, 1, 64, 0), (1024, 2, 1, 64, 0),
                       (1025, 1, 1, 128, 1000), (257, 0, 3, 64, 0), (129, 0, 3, 128, 1000)]
POLICY = {"tree_memory_gib": 4, "reserve_gib": 32, "background_memory_gib": 8,
          "allow_bounded_builds": True}
CLAIMS = {"adapter_rtl_pass": False, "algorithm_rtl_admitted": False,
          "hardware_timing_admitted": False, "board_admitted": False, "publication_match": False}


def prepare(compilation, storage, output, vivado_bin):
    checked = review.run(compilation, storage, output / "compile-review")
    manifest = json.loads((compilation / "manifest.json").read_text())
    rows = [row for row in manifest["compiles"] if row["kernel"] == "pma_to_regraph_adapter"]
    if len(rows) != 1:
        raise ValueError("one freshly compiled production adapter required")
    flags = checked["interfaces"]["pma_to_regraph_adapter"]["macros"]
    required = {"SHARDED_PMA": "1", "DESTINATION_ONLY": "1", "BANK_STREAM": "1",
                "BANK_FIFO_LINES": "256", "DIRECTORY_TILE_ROWS": "1024", "ROW_LINE_READ": "1"}
    if any(flags.get("GRASU_REGRAPH_" + name) != value for name, value in required.items()):
        raise ValueError("fresh destination-only sharded bank-stream ABI required")
    work = output / "rtl"
    work.mkdir()
    rtl = extract_rtl(Path(rows[0]["xo"]), work)
    for relative in (BENCH, BANK_BENCH):
        shutil.copyfile(ROOT / relative, work / Path(relative).name)
    (work / "run.tcl").write_text("run all\nquit\n")
    pins = [*checked["inputs"], identity(output / "compile-review/results.json"),
            *map(identity, [*rtl, ROOT / BENCH, ROOT / BANK_BENCH,
                           *[work / Path(name).name for name in (BENCH, BANK_BENCH)], work / "run.tcl"])]
    tools = {name: vivado_bin / name for name in ("xvlog", "xelab", "xsim")}
    pins.extend(map(identity, tools.values()))
    return {"algorithm": manifest["algorithm"], "integration_revision": manifest["integration_revision"],
            "xo": identity(Path(rows[0]["xo"])), "pins": pins,
            "compile_review_status": checked["status"], "trials": TRIALS,
            "clock_period_ns": 10, "reset_between_trials": True,
            "memory_model": "ordered_AR_to_first_RVALID_latency_plus_one_clock_no_DRAM_bank_timing",
            "packet_scope": "opaque_sharded_destination_bits_padding_and_sidebands_not_graph_algorithm",
            "commands": {
                "compile": [str(tools["xvlog"]), "--sv", Path(BANK_BENCH).name]
                           + [path.name for path in rtl if path.suffix == ".v"],
                "elaborate": [str(tools["xelab"]), "adapter_axi_tb", "-s", "adapter_axi"],
                "simulate": [str(tools["xsim"]), "adapter_axi", "-tclbatch", "run.tcl"]}, **CLAIMS}


def require_execution(record):
    if record["exit_code"] != 0 or record["stop_reason"] != "process_exit" or \
            record["cleanup_snapshot_error"] is not None or record["tree_memory_gib"] != 4 or \
            record["reserve_gib"] != 32 or record["timeout_seconds"] != 180 or \
            record["peak_tree_rss_kib"] > 4 * 1024**2 or record["minimum_available_bytes"] < 32 * 1024**3:
        raise ValueError("adapter RTL command failed its resource/outcome gate")


def run(compilation, storage, output, xilinx, platform, compatibility, shim):
    compilation, storage, output, xilinx, platform, compatibility, shim = (
        path.resolve() for path in (compilation, storage, output, xilinx, platform, compatibility, shim))
    output.mkdir(parents=True, exist_ok=False)
    group = current()
    report = {"status": "PREPARING_ADAPTER_RTL", "errors": [], "host": socket.gethostname(),
              "policy": POLICY, "steps": {}, **CLAIMS}
    save = lambda: atomic_write_json(output / "execution.json", report)
    lease = Lease(Path.home() / ".cache/spine-cycle-sim/compiler-reservations", group)
    save()
    try:
        report["containment"] = verify(group, memory_gib=4)
        if shutil.disk_usage(output).free < 4 * 1024**3:
            raise ValueError("at least 4 GiB free RTL scratch disk required")
        for name in ("tmp", "user-data"):
            (output / name).mkdir()
        effective, contract = environment.capture(shim, output, xilinx, platform, compatibility)
        atomic_write_json(output / "environment.json", contract)
        manifest = prepare(compilation, storage, output, xilinx / "Vivado/2024.1/bin")
        report.update(algorithm=manifest["algorithm"], integration_revision=manifest["integration_revision"])
        runners = sorted({Path(module.__file__) for name, module in sys.modules.copy().items()
            if name.startswith("spine_cycle_sim.experiments") and getattr(module, "__file__", None)})
        pins = manifest["pins"]
        pins.extend([*contract["pins"], *map(identity, runners), identity(Path(sys.executable)),
                     identity(output / "environment.json")])
        atomic_write_json(output / "manifest.json", {**manifest, "policy": POLICY, "timeout_seconds": 180})
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
                raise TimeoutError("full finite RTL budgets plus reserve do not fit")
            time.sleep(10)
        report["status"] = "ENVIRONMENT_PREFLIGHT"
        save()
        report["preflight"] = probe.run(output, effective, contract)
        pins.append(identity(output / "preflight/results.json"))
        for step, command in manifest["commands"].items():
            unchanged(pins)
            require_unchanged(contract, effective)
            report.update(status="RUNNING_ADAPTER_RTL_NOT_FPGA_TIMING", current_step=step)
            save()
            record = run_link(command, output / "rtl", output / step, environment=effective,
                              timeout=180, tree_memory_gib=4, reserve_gib=32, poll_seconds=0.5)
            report["steps"][step] = record
            save()
            require_execution(record)
        unchanged(pins)
        report["trials"] = parse_trace((output / "simulate.stdout.txt").read_text(), TRIALS)
        report.update(status="FRESH_ADAPTER_AXI_RTL_PASS_NOT_ALGORITHM_RTL_OR_BOARD", adapter_rtl_pass=True)
    except BaseException as error:
        report["status"] = "FAILED_RETAINED"
        report["errors"].append(repr(error))
        raise
    finally:
        lease.release()
        report["memory_events_after"] = (group / "memory.events").read_text()
        save()
    return report
