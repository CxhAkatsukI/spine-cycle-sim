"""Bounded diagnostic of actual G-to-R handoff against common-warm Spine."""

import argparse
import json
import os
from pathlib import Path
import subprocess
import tarfile

from spine_cycle_sim.experiments.campaign_runtime import atomic_write_json
from ...upstream_controls.execution import run_bounded
from ..r_credits.freeze import ROOT, pin
from ..r_bank_stream import cached_core, runtime
from .analysis import record, summarize


def run(output, reference, cpu):
    if cpu not in os.sched_getaffinity(0):
        raise ValueError("CPU outside allowed affinity")
    compiler = Path("/usr/bin/g++").resolve()
    core, pins = cached_core.validate_convergence(ROOT, reference, compiler,
        complete_status="GATHER_REUSE_COMPLETE_SIMULATOR_PREDICTION")
    output.mkdir(parents=True, exist_ok=False)
    (output / "raw").mkdir()
    (output / "build").mkdir()
    sources = sorted(p for p in (ROOT / "cpp/tests").rglob("*") if p.is_file())
    sources += sorted(p for p in Path(__file__).parent.glob("*.py"))
    sources += [ROOT / "configs/architectures/spine_owner_fifo_sssp_hls_v1.json"]
    pins += [pin(p) for p in sources]
    with tarfile.open(output / "harness_sources.tar.gz", "w:gz") as archive:
        for source in sources:
            archive.add(source, arcname=source.relative_to(ROOT), recursive=False)
    pins.append(pin(output / "harness_sources.tar.gz"))
    report = dict(status="RUNNING_EXPLORATORY_DEVICE_PREDICTION", baseline_admitted=False,
        host_time_included=False, pins=pins, steps=[], rows=[], comparisons=[], failures=[],
        git_head=subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT, text=True).strip(),
        core_rebuilt=False, reused_core_tests=37, cpu=cpu)
    def save():
        atomic_write_json(output / "results.json", report)
    save()
    selected = runtime.settings(runtime.FRESH_CPU, 1)
    try:
        with runtime.reservation(output, selected) as guard:
            report["admission"] = guard
            executable = output / "build/warm_spine_comparison"
            command = [str(compiler), "-O3", "-DNDEBUG", "-std=gnu++20", "-Wall", "-Wextra",
                "-Wpedantic", "-Werror", "-I" + str(ROOT / "cpp/include"),
                str(ROOT / "cpp/tests/evaluation_impact/warm_comparison/main.cpp"),
                "-o", str(executable), str(core / "liboriginal_regraph_cycle.a"),
                str(core / "libspine_cycle_core.a")]
            step = run_bounded(command, ROOT, output / "raw/build", timeout=180,
                               memory_gib=4, reserve_gib=24)
            report["steps"].append(step)
            save()
            if step["exit_code"] or step["timed_out"]:
                raise ValueError("new harness compilation failed; evidence retained")
            pins.append(pin(executable))
            for workload in ("smoke", "amazon"):
                source = "smoke" if workload == "smoke" else str(reference.parent / "inputs/warm_update")
                for latency in (64, 128):
                    for arm, reverse in (("gr", 0), ("gr", 1), ("spine", 0)):
                        name = f"{workload}_lat{latency}_{arm}_order{reverse}"
                        directory = output / name
                        directory.mkdir()
                        print("START " + name, flush=True)
                        command = ["taskset", "-c", str(cpu), str(executable), source,
                                   str(directory), str(latency), str(reverse), "150000000", arm]
                        step = run_bounded(command, ROOT, output / "raw" / name,
                            timeout=600, memory_gib=4, reserve_gib=24)
                        report["steps"].append(step)
                        save()
                        row = record(step, directory, workload, latency, arm, reverse)
                        report["rows"].append(row)
                        print("DONE " + name + " " + json.dumps(row["result"]), flush=True)
                        save()
            report["comparisons"] = summarize(report["rows"])
            if any(pin(Path(p["path"])) != p for p in pins):
                raise ValueError("frozen numerical source, input or harness changed")
            report["pins_unchanged"] = True
            report["status"] = "COMPLETE_EXPLORATORY_DEVICE_PREDICTION"
            save()
    except Exception as error:
        report["status"] = "FAILED_RETAINED"
        report["failures"].append(repr(error))
        save()
        raise
    return report


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--reference", type=Path, required=True)
    parser.add_argument("--cpu", type=int, required=True)
    args = parser.parse_args()
    result = run(args.output.resolve(), args.reference.resolve(), args.cpu)
    print(json.dumps({"status": result["status"], "comparisons": result["comparisons"]}), flush=True)
