"""Independent, finite-memory author-source compilation and routing supervisor."""

import json
from pathlib import Path
import subprocess
import sys

from spine_cycle_sim.experiments.campaign_runtime import atomic_write_json
from spine_cycle_sim.experiments.sharded_k4_stages.link_runtime import run_link
from spine_cycle_sim.experiments.sharded_k4_stages.row_line.directory_tile.hardware.concurrent import Lease
from spine_cycle_sim.experiments.sharded_k4_stages.row_line.directory_tile.hardware.containment import current, other_builds, verify
from spine_cycle_sim.experiments.upstream_controls.execution import available_memory_bytes, run_bounded
from .. import artifact, checkpoint_run, control_delivery, study
from . import configuration as config, gates, placement as physical, snapshot


def runner_pins() -> list[dict]:
    files = {Path(module.__file__).resolve() for name, module in list(sys.modules.items())
             if name.startswith("spine_cycle_sim.") and (getattr(module, "__file__", "") or "").endswith(".py")}
    files.update(Path(__file__).parent.glob("*.py"))
    return [artifact.identity(path) for path in sorted(files)]


def prerequisites(audit: Path, control: Path) -> list[dict]:
    reference = json.loads((audit / "results.json").read_text())
    validated = json.loads((control / "results.json").read_text())
    if reference["status"] != study.STATUS or reference["errors"]:
        raise ValueError("passing independent author input audit required")
    control_delivery.terminal(validated)
    audit_pin = artifact.identity(audit / "results.json")
    if audit_pin not in validated["pins"]:
        raise ValueError("guarded host validation belongs to another audit")
    pins = [audit_pin, artifact.identity(control / "results.json"), *reference["pins"], *validated["pins"]]
    snapshot.unchanged(pins)
    return pins


def run(root: Path, upstream: Path, audit: Path, control: Path, captured_environment: Path,
        output: Path, *, topology: str = config.DEFAULT_TOPOLOGY,
        placement: str = physical.DEFAULT) -> dict:
    physical.validate(topology, placement)
    little, big = config.counts(topology)
    kernels = config.kernels(topology)
    output.mkdir(parents=True, exist_ok=False)
    report = {"status": "PREPARED", "errors": [], "steps": [], "xos": [], "pins": [],
              "policy": config.POLICY, "clock_mhz": config.CLOCK_MHZ,
              "configuration": topology, "little": little, "big": big, "placement": placement,
              "board_programmed": False, "hardware_timing_measured": False, "publication_match": False,
              "claim": "clean_author_source_same_platform_clock_control_not_publication_reproduction"}
    lease = None

    def save():
        atomic_write_json(output / "results.json", report)

    save()
    try:
        group = current()
        report["containment"] = verify(group, memory_gib=config.POLICY["tree_memory_gib"])
        lease = Lease(Path.home() / ".cache/spine-cycle-sim/compiler-reservations", group)
        report["admission"] = lease.sample(available_memory_bytes(), other_builds(), config.POLICY, commit=True)
        save()
        if not report["admission"]["admitted"]:
            raise RuntimeError("full finite peer budgets plus reserve do not fit; no tools launched")
        report["pins"] = prerequisites(audit, control) + runner_pins()
        captured = json.loads(captured_environment.read_text())
        snapshot.unchanged(captured["pins"])
        report["pins"] += [artifact.identity(captured_environment), *captured["pins"],
                           artifact.identity(config.COMPILER), artifact.identity(config.PLATFORM),
                           artifact.identity(config.GENERATOR_PYTHON), artifact.identity(Path(sys.executable).resolve())]
        report["generator_python_version"] = subprocess.check_output(
            [str(config.GENERATOR_PYTHON), "--version"], text=True, timeout=10).strip()
        effective = checkpoint_run.environment(captured_environment, output)
        if (effective.get("XILINX_VITIS") != str(config.COMPILER.parents[1]) or
                effective.get("XILINX_HLS") != "/data/yxx/tools/xilinx/Vitis_HLS/2024.1"):
            raise ValueError("reviewed 2024.1 Vitis/HLS environment required")
        atomic_write_json(output / "environment.json", {"values": effective, "license_hashes": {}})
        report["source_revision"] = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=root, text=True).strip()
        report["worktree_status"] = subprocess.check_output(["git", "status", "--porcelain"], cwd=root, text=True).splitlines()
        prepared = snapshot.prepare(root, upstream, output, topology)
        report["source_snapshot"] = prepared
        report["pins"] += prepared["pins"]
        source = Path(prepared["source"])
        placed = physical.prepare(source, output, topology, placement)
        report["physical_configuration"] = placed
        report["pins"] += placed["pins"]
        entries = snapshot.prepare_entries(source, output, topology)
        report["pins"] += entries
        manifest = {"source": prepared, "defines": config.defines(topology), "clock_mhz": config.CLOCK_MHZ,
                    "configuration": topology, "little": little, "big": big,
                    "physical_configuration": placed,
                    "compatibility_entries": entries, "legacy_uint": "unsigned int; sizeof == 4",
                    "compilations": {name: config.compile_command(source, output, name, topology) for name in kernels},
                    "link": config.link_command(source, output, topology,
                                                connectivity=Path(placed["config"])), "policy": config.POLICY,
                    "compile_timeout_seconds": 1800, "link_timeout_seconds": 21600,
                    "pins": report["pins"]}
        atomic_write_json(output / "manifest.json", manifest)
        report["pins"].append(artifact.identity(output / "manifest.json"))
        (output / "xo").mkdir()

        def step(name, command, timeout):
            snapshot.unchanged(report["pins"])
            report["status"] = name.upper() + "_RUNNING"
            save()
            print(report["status"], flush=True)
            execution = run_link(command, output, output / name, timeout=timeout,
                                 tree_memory_gib=40, reserve_gib=32, environment=effective)
            report["steps"].append({"id": name, **execution})
            save()
            if execution["exit_code"] or execution["stop_reason"] != "process_exit" or execution["cleanup_snapshot_error"]:
                raise RuntimeError("build failed or was safely stopped: " + name)
            snapshot.unchanged(report["pins"])

        for name, command in manifest["compilations"].items():
            step("compile_" + name, command, manifest["compile_timeout_seconds"])
            xo = gates.inspect_xo(output / "xo" / (name + ".hw.xo"), name, topology)
            hls = gates.inspect_hls(output / "compile" / name, name)
            report["xos"].append({"abi": xo, "hls": hls})
            report["pins"] += [xo["xo"], hls["report"]]
            save()
        step("route", manifest["link"], manifest["link_timeout_seconds"])
        binary = output / config.binary_name(topology)
        report["xclbin"] = artifact.identity(binary)
        metadata = output / "metadata"
        metadata.mkdir()
        report["extraction"] = run_bounded(artifact.dump_command(binary, metadata, checkpoint_run.UTILITY),
            output, output / "extract", timeout=120, memory_gib=2, reserve_gib=32)
        if report["extraction"]["exit_code"] or report["extraction"]["timed_out"]:
            raise ValueError("fresh xclbin metadata extraction failed")
        report["analysis"] = gates.inspect_routed(metadata, output / "link/reports", topology)
        snapshot.unchanged(report["pins"])
        report["status"] = report["analysis"]["status"]
    except BaseException as error:
        report["status"] = "FAILED_RETAINED"
        report["errors"].append(repr(error))
        save()
        raise
    finally:
        if lease is not None:
            lease.release()
        report["memory_events_after"] = (current() / "memory.events").read_text()
        save()
    return report
