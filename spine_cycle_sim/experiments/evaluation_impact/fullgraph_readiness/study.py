"""Bounded offline host preparation while independent FPGA builds continue."""

from pathlib import Path
import shutil
import subprocess
import sys
import time

from spine_cycle_sim.experiments.campaign_runtime import atomic_write_json
from spine_cycle_sim.experiments.sharded_k4_stages.link_runtime import run_link
from spine_cycle_sim.experiments.sharded_k4_stages.row_line.directory_tile.hardware.concurrent import Lease
from spine_cycle_sim.experiments.sharded_k4_stages.row_line.directory_tile.hardware.containment import current, other_builds, verify
from spine_cycle_sim.experiments.upstream_controls.execution import available_memory_bytes, dependency_identities
from . import analysis, diagnostics, preparation

POLICY = {"tree_memory_gib": 24, "reserve_gib": 32, "allow_bounded_builds": True}


def run(integration, manifest, output, xrt, hls, *, wait_seconds=64800):
    if type(wait_seconds) is not int or not 1 <= wait_seconds <= 86400:
        raise ValueError("memory wait must be between one second and one day")
    output.mkdir(parents=True, exist_ok=False)
    report = {"status": "PREPARING", "errors": [], "steps": [], "cases": [], "smokes": [], "pins": [],
              "policy": POLICY, "board_programmed": False, "hardware_timing_measured": False,
              "publication_match": False, "production_baseline_admitted": False,
              "scope": "unchanged current production host; insertion/u8; graph capacity and CPU oracle only"}
    save = lambda: atomic_write_json(output / "results.json", report)
    lease = None
    save()
    try:
        group = current()
        report["containment"] = verify(group, memory_gib=24)
        if int(report["containment"]["limits"]["memory.max"]) != 24 * 1024**3:
            raise ValueError("exact 24-GiB complete preparation cgroup required")
        compiler = Path(shutil.which("g++") or "/missing/compiler").resolve()
        library = xrt / "lib/libxilinxopencl.so"
        runners = {Path(module.__file__) for name, module in sys.modules.copy().items()
                   if name.startswith("spine_cycle_sim.experiments") and getattr(module, "__file__", None)}
        runners.update(Path(__file__).parent.glob("*.py"))
        runners.update((Path(__file__).parent / "fixtures").glob("*.graph"))
        report["pins"] = [preparation.identity(path) for path in (compiler, library, Path(sys.executable), *sorted(runners))]
        report["compiler_version"] = subprocess.check_output([str(compiler), "--version"], text=True)
        report["python_version"] = sys.version
        temporary = output / "tmp"
        temporary.mkdir()
        report["environment"] = {"PATH": "/usr/bin:/bin", "HOME": str(Path.home()),
                                 "LANG": "C", "LC_ALL": "C", "TMPDIR": str(temporary)}
        prepared = preparation.freeze(integration, manifest, output)
        report["source_revision"] = prepared["revision"]
        report["matrix"] = prepared["rows"]
        report["pins"] += prepared["pins"]
        lease = Lease(Path.home() / ".cache/spine-cycle-sim/compiler-reservations", group)
        deadline = time.monotonic() + wait_seconds
        report["status"] = "WAITING_FOR_MEMORY_NOT_FOR_OTHER_TOOLS_TO_EXIT"
        save()
        while True:
            preparation.unchanged(report["pins"])
            report["admission"] = lease.sample(available_memory_bytes(), other_builds(), POLICY, commit=True)
            save()
            if report["admission"]["admitted"]:
                break
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise TimeoutError("full budgets and reserve did not fit before deadline; no child launched")
            time.sleep(min(10, remaining))
        preparation.unchanged(report["pins"], full=True)

        def step(label, command, timeout):
            preparation.unchanged(report["pins"])
            report["status"] = "RUNNING_" + label
            save()
            result = run_link(command, output, output / "raw" / label, timeout=timeout,
                              tree_memory_gib=24, reserve_gib=32, environment=report["environment"])
            report["steps"].append({"label": label, **result})
            save()
            preparation.unchanged(report["pins"])
            if result["exit_code"] or result["stop_reason"] != "process_exit" or result["cleanup_snapshot_error"]:
                raise RuntimeError("preparation child failed or was safely stopped: " + label)
            return result

        binaries = {}
        for algorithm in preparation.ALGORITHMS:
            binary = output / algorithm
            step("compile_" + algorithm,
                preparation.compile_command(compiler, Path(prepared["source"]), algorithm, binary, xrt, hls), 300)
            report.setdefault("compiler_diagnostics", {})[algorithm] = diagnostics.review(
                *((output / "raw" / ("compile_" + algorithm + suffix)).read_text()
                  for suffix in (".stdout.txt", ".stderr.txt")))
            binaries[algorithm] = binary
            report["pins"] += [preparation.identity(binary), *dependency_identities(binary.with_suffix(".d"), output)]
            # Dependency helper owns parsing, while this study owns drift stamps.
            report["pins"] = [pin if "stat" in pin else preparation.identity(Path(pin["path"])) for pin in report["pins"]]
            save()

        smokes = preparation.smokes(output)
        report["pins"] += [preparation.identity(Path(row["graph"])) for row in smokes]
        for row in [*smokes, *report["matrix"]]:
            label = row["dataset"] + "_" + row["algorithm"]
            case = {"dataset": row["dataset"], "algorithm": row["algorithm"], "status": "RUNNING"}
            smoke = row["dataset"] == "SMOKE"
            report["smokes" if smoke else "cases"].append(case)
            save()
            try:
                step(label, preparation.prepare_command(binaries[row["algorithm"]], row, output / (label + ".unused-result")), 1800)
                case.update(analysis.analyze(row, (output / "raw" / (label + ".stdout.txt")).read_text(),
                                             (output / "raw" / (label + ".stderr.txt")).read_text()))
            except (ValueError, RuntimeError, KeyError) as error:
                case.update(status="FAILED_RETAINED", error=repr(error))
            preparation.unchanged(report["pins"])
            save()
            if smoke and case["status"] != "PASS":
                raise RuntimeError("six-partition correctness smoke failed; no full-graph child launched")
        preparation.unchanged(report["pins"], full=True)
        report["status"] = analysis.decision(report["cases"])
    except BaseException as error:
        report["status"] = "FAILED_RETAINED"
        report["errors"].append(repr(error))
        raise
    finally:
        if lease is not None:
            lease.release()
        report["memory_events_after"] = (current() / "memory.events").read_text()
        save()
    return report
