"""Measure only warm-batch CPU preparation, under the existing finite run guard."""

import argparse
import json
import os
from pathlib import Path
import platform
import subprocess
import tarfile

from spine_cycle_sim.experiments.campaign_runtime import atomic_write_json
from ...original_regraph_inputs.analysis import records
from ...upstream_controls.execution import available_memory_bytes, run_bounded
from ..r_credits.freeze import ROOT, pin
from ..r_bank_stream import cached_core, runtime
from .a4_analysis import reference_rows
from . import host_analysis as analysis


def run(output, reference, comparison, cpu):
    if cpu not in os.sched_getaffinity(0):
        raise ValueError("CPU outside allowed affinity")
    compiler = Path("/usr/bin/g++").resolve()
    core, pins = cached_core.validate_convergence(ROOT, reference, compiler,
        complete_status="GATHER_REUSE_COMPLETE_SIMULATOR_PREDICTION")
    warm = reference_rows(json.loads(comparison.read_text()), comparison.parent)
    output.mkdir(parents=True, exist_ok=False)
    (output / "raw").mkdir()
    (output / "build").mkdir()
    sources = [ROOT / ("cpp/tests/evaluation_impact/warm_comparison/" + name)
               for name in ("host_main.cpp", "host_preparation.hpp")]
    sources += sorted(Path(__file__).parent.glob("host_*.py"))
    pins += [pin(p) for p in sources] + [pin(comparison)]
    for row in warm:
        pins += [pin(Path(row["resources"][key])) for key in ("stdout", "stderr")]
    with tarfile.open(output / "harness_sources.tar.gz", "w:gz") as archive:
        for path in sources:
            archive.add(path, arcname=path.relative_to(ROOT), recursive=False)
    pins.append(pin(output / "harness_sources.tar.gz"))
    governor = Path(f"/sys/devices/system/cpu/cpu{cpu}/cpufreq/scaling_governor")
    report = dict(status="RUNNING_PARTIAL_HOST_PREPARATION_MEASUREMENT", baseline_admitted=False,
        full_host_time_included=False, pins=pins, steps=[], rows=[], comparisons=[], failures=[],
        warm_rows=warm, cpu=cpu, uname=list(platform.uname()), cpuinfo=Path("/proc/cpuinfo").read_text(),
        governor=governor.read_text().strip() if governor.exists() else None,
        core_rebuilt=False, reused_core_tests=37,
        excluded=["initial graph/state load", "XRT arguments and buffer management", "DMA",
                  "seed-list application to resident active state", "active clearing",
                  "kernel launch/wait", "round status readback/relaunch", "final readback"],
        git_head=subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT, text=True).strip())
    def save():
        atomic_write_json(output / "results.json", report)
    def execute(label, command):
        print("START " + label, flush=True)
        step = run_bounded(command, ROOT, output / "raw" / label, timeout=180,
                           memory_gib=4, reserve_gib=24)
        report["steps"].append(step)
        save()
        if step["exit_code"] or step["timed_out"]:
            raise ValueError(label + " failed; raw evidence retained")
        return step
    save()
    try:
        with runtime.reservation(output, runtime.settings(runtime.FRESH_CPU, 1)) as guard:
            report["admission"] = guard
            executable = output / "build/warm_host_preparation"
            execute("build", [str(compiler), "-O3", "-DNDEBUG", "-std=gnu++20", "-Wall",
                "-Wextra", "-Wpedantic", "-Werror", "-I" + str(ROOT / "cpp/include"), str(sources[0]),
                "-o", str(executable), str(core / "libspine_cycle_core.a")])
            pins.append(pin(executable))
            execute("self_test", ["taskset", "-c", str(cpu), str(executable), "--self-test"])
            for workload in ("smoke", "amazon"):
                identity = next(r["input"] for r in warm if r["workload"] == workload)
                path = output / (workload + ".batch.txt")
                path.write_text(f"{identity['vertices']} {len(identity['updates'])}\n" + "".join(
                    " ".join(map(str, update)) + "\n" for update in identity["updates"]))
                pins.append(pin(path))
            # Alternate workloads across process repetitions; each process alternates arm order.
            for repeat in range(analysis.REPETITIONS):
                for workload in (("smoke", "amazon") if repeat % 2 == 0 else ("amazon", "smoke")):
                    step = execute(f"{workload}_repeat{repeat}", ["taskset", "-c", str(cpu),
                        str(executable), str(output / (workload + ".batch.txt"))])
                    result = records(Path(step["stdout"]).read_text(), "HOST_PREPARATION ")
                    if len(result) != 1:
                        raise ValueError("one CPU measurement record required")
                    report["rows"].append(dict(workload=workload, repeat=repeat, result=result[0], resources=step))
                    save()
            report["comparisons"] = analysis.summarize(report["rows"], warm)
            group = Path(guard["cgroup"]["path"])
            memory = dict(available_bytes=available_memory_bytes(),
                peak_bytes=int((group / "memory.peak").read_text()),
                swap_bytes=int((group / "memory.swap.current").read_text()))
            atomic_write_json(output / "final_memory.json", memory)
            if memory["available_bytes"] < 24 * 1024**3 or memory["swap_bytes"] != 0:
                raise ValueError("final memory reserve or zero-swap gate failed")
            if any(pin(Path(p["path"])) != p for p in pins):
                raise ValueError("pinned numerical source, input, executable or harness changed")
            report["pins_unchanged"] = True
            report["status"] = analysis.STATUS
            save()
            analysis.validate(report, lambda name: (output / name).read_bytes())
    except Exception as error:
        report["status"] = "FAILED_RETAINED"
        report["failures"].append(repr(error))
        save()
        raise
    return report


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("output", "reference", "comparison"):
        parser.add_argument("--" + name, type=Path, required=True)
    parser.add_argument("--cpu", type=int, required=True)
    args = parser.parse_args()
    result = run(args.output.resolve(), args.reference.resolve(), args.comparison.resolve(), args.cpu)
    print(json.dumps(dict(status=result["status"], comparisons=result["comparisons"])), flush=True)
