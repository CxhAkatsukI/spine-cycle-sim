"""Verify rolling updates and measure matched host preparation with explicit transfer assumptions."""

import argparse
import json
import os
from pathlib import Path
import subprocess

from spine_cycle_sim.experiments.campaign_runtime import atomic_write_json
from ...upstream_controls.execution import run_bounded
from ..r_bank_stream import runtime
from ..r_credits.freeze import ROOT, pin
from . import analysis, study


def run(output, manifest, cpu, update_count, batch_count=10,
        memory_profile=runtime.FRESH_CPU, admission_wait_seconds=600):
    if cpu not in os.sched_getaffinity(0):
        raise ValueError("CPU outside allowed affinity")
    case = json.loads(manifest.read_text())
    compiler = Path("/usr/bin/g++").resolve()
    dram_config = ROOT / "configs/memory/HBM2_1ch_x128_summary_only.ini"
    sst_config = Path(__file__).with_name("sst_config.py")
    inputs = [Path(case[name]) for name in ("graph", "updates")]
    if type(update_count) is not int or not 1 < batch_count <= update_count:
        raise ValueError("multiple nonempty insertion batches required")
    paths = [manifest, *inputs, compiler, study.SST, dram_config, study.DRAM / "libdramsim3.so",
             study.DRAM / "src/dramsim3.h", ROOT / "CMakeLists.txt", ROOT / "cpp/CMakeLists.txt",
             Path(runtime.__file__), Path(__file__).resolve()]
    for directory in ("cpp/src", "cpp/include", "cpp/sst", "cpp/tests",
                      "spine_cycle_sim/experiments/evaluation_impact/figure_refresh"):
        paths.extend(p for p in sorted((ROOT / directory).rglob("*"))
                     if p.is_file() and p.suffix in (".cpp", ".hpp", ".py"))
    output.mkdir(parents=True, exist_ok=False)
    report = dict(status="RUNNING", cpu=cpu, host_included=True, steps={}, rows={},
                  comparisons={}, compiler_version=subprocess.check_output([str(compiler), "--version"], text=True),
                  boundary="one initial layout/upload plus chronological batch packing/upload, per-batch launch/sync and device maintenance; no propagation",
                  transfer_scope="logical payloads, shared G row/head tables including sentinel; not padded BO allocation",
                  excluded="file parsing, oracle, runtime allocation, XRT scheduling and readback",
                  pins=[pin(p) for p in sorted(set(paths))],
                  git_head=subprocess.check_output(["git", "rev-parse", "HEAD"],
                                                   cwd=ROOT, text=True).strip())
    if memory_profile not in (runtime.FRESH_CPU, runtime.LARGE_CPU):
        raise ValueError("only the finite fresh-core and large-input CPU profiles are supported")
    profile = runtime.settings(memory_profile, 1)
    child_memory_gib = 32 if memory_profile == runtime.LARGE_CPU else 4
    runtime.wait_budget(admission_wait_seconds)

    def save():
        atomic_write_json(output / "results.json", report)

    def execute(name, command, timeout):
        row = run_bounded(command, ROOT, output / "raw" / name,
                          timeout=timeout, memory_gib=child_memory_gib,
                          reserve_gib=profile["policy"]["reserve_gib"])
        report["steps"][name] = row
        save()
        if row["exit_code"] or row["timed_out"]:
            raise ValueError(f"{name} failed; see retained output")
        return row

    save()
    try:
        with runtime.reservation(output, profile, wait_seconds=admission_wait_seconds) as guard:
            report["admission"] = guard
            build = output / "build"
            execute("configure", ["cmake", "-S", str(ROOT), "-B", str(build), "-G", "Ninja",
                    "-DCMAKE_BUILD_TYPE=Release", "-DCMAKE_EXPORT_COMPILE_COMMANDS=ON"], 120)
            execute("core", ["cmake", "--build", str(build), "--parallel", "2", "--target",
                    "spine_cycle_core", "original_regraph_cycle", "grasu_cycle_tests",
                    "grasu_resident_tests"], 650)
            execute("core_tests", ["ctest", "--test-dir", str(build), "--output-on-failure",
                    "-R", "^grasu_(cycle|resident)_tests$"], 180)
            plugin = build / "libfigure_refresh.so"
            execute("plugin", study.plugin_command(compiler, build / "cpp", plugin), 240)
            report["build_pins"] = [pin(p) for p in (plugin, build / "CMakeCache.txt",
                build / "compile_commands.json", build / "cpp/libspine_cycle_core.a",
                build / "cpp/liboriginal_regraph_cycle.a")]
            for label, graph, updates, count, batches in (
                ("smoke", "smoke", "", 3, 3),
                ("trace", *(str(p) for p in inputs), update_count, batch_count),
            ):
                for arm in ("spine", "gr"):
                    name = label + "_" + arm
                    directory = output / name
                    directory.mkdir()
                    config = directory / "config.json"
                    atomic_write_json(config, dict(mode="update", arm=arm, graph=graph,
                        updates=updates, batches=batches, output=str(directory),
                        dram_config=str(dram_config), maximum=150000000))
                    step = execute(name, ["env", "LD_LIBRARY_PATH=" + str(study.DRAM), "taskset",
                        "-c", str(cpu), str(study.SST), "--no-env-config",
                        "--add-lib-path=" + str(build), str(sst_config), "--", str(config)], 900)
                    report["rows"][name] = dict(
                        **analysis.persistent_device(step, arm=arm, updates=count, batch_count=batches),
                        config=pin(config), backend=pin(directory / "backend.json"),
                        stdout=pin(Path(step["stdout"])))
                    save()
                    host_directory = output / (name + "_host")
                    host_directory.mkdir()
                    host_config = host_directory / "config.json"
                    atomic_write_json(host_config, dict(mode="host", arm=arm, graph=graph,
                        updates=updates, batches=batches, output=str(host_directory)))
                    host_step = execute(name + "_host", ["env", "LD_LIBRARY_PATH=" + str(study.DRAM),
                        "taskset", "-c", str(cpu), str(study.SST), "--no-env-config",
                        "--add-lib-path=" + str(build), str(sst_config), "--", str(host_config)], 900)
                    report["rows"][name]["host"] = analysis.persistent_host(
                        host_step, arm=arm, updates=count, batch_count=batches)
                    report["rows"][name]["host_evidence"] = dict(config=pin(host_config),
                        stdout=pin(Path(host_step["stdout"])))
                    save()
                report["comparisons"][label] = analysis.persistent_comparison(
                    {arm: report["rows"][label + "_" + arm] for arm in ("spine", "gr")},
                    updates=count, batch_count=batches)
                save()
            if any(pin(Path(row["path"])) != row for row in report["pins"] + report["build_pins"]):
                raise ValueError("pinned source, build or input changed")
            report["status"] = "PERSISTENT_PAIRED_SETUP_PREDICTION"
    except Exception as error:
        report.update(status="FAILED_RETAINED", error=repr(error))
        raise
    finally:
        save()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--cpu", type=int, required=True)
    parser.add_argument("--update-count", type=int, required=True)
    parser.add_argument("--batch-count", type=int, default=10)
    parser.add_argument("--memory-profile", choices=(runtime.FRESH_CPU, runtime.LARGE_CPU),
                        default=runtime.FRESH_CPU)
    parser.add_argument("--admission-wait-seconds", type=int, default=600)
    args = parser.parse_args()
    run(args.output.resolve(), args.manifest.resolve(), args.cpu, args.update_count,
        args.batch_count, args.memory_profile, args.admission_wait_seconds)
