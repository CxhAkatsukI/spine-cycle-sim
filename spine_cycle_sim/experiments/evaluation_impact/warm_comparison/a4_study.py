"""Bounded original-A4 control for the already completed three-insertion demo."""

import argparse
import json
import os
from pathlib import Path
import subprocess
import tarfile

from spine_cycle_sim.experiments.campaign_runtime import atomic_write_json
from ...upstream_controls.execution import run_bounded, dependency_identities
from ...upstream_controls.sources import read_pins, verify_snapshot, prepare_regraph
from ..r_credits.freeze import ROOT, pin
from ..r_bank_stream import cached_core, runtime
from .a4_analysis import a4_record, reference_rows, summarize
from .a4_preparation import describe_layout, layout_command


def run(output, reference, comparison, cpu, source, xrt_include):
    if cpu not in os.sched_getaffinity(0):
        raise ValueError("CPU outside allowed affinity")
    compiler = Path("/usr/bin/g++").resolve()
    core, pins = cached_core.validate_convergence(ROOT, reference, compiler,
        complete_status="GATHER_REUSE_COMPLETE_SIMULATOR_PREDICTION")
    warm = reference_rows(json.loads(comparison.read_text()), comparison.parent)
    upstream = read_pins(ROOT / "docs/experiments/comparisons/grasu_regraph_stage_validation/source_pins.json")
    verified = verify_snapshot(source, upstream["regraph"])
    output.mkdir(parents=True, exist_ok=False)
    (output / "raw").mkdir()
    (output / "build").mkdir()
    sources = sorted(p for p in (ROOT / "cpp/tests").rglob("*") if p.is_file())
    sources += sorted(p for p in Path(__file__).parent.glob("*.py"))
    pins += [pin(p) for p in sources] + [pin(comparison)]
    for row in warm:
        pins += [pin(Path(row["resources"][key])) for key in ("stdout", "stderr")]
    with tarfile.open(output / "harness_sources.tar.gz", "w:gz") as archive:
        for item in sources:
            archive.add(item, arcname=item.relative_to(ROOT), recursive=False)
    report = dict(status="RUNNING_SAME_BATCH_A4_PREDICTION", baseline_admitted=False,
        host_time_included=False, pins=pins, source_pin=verified, steps=[], rows=[],
        warm_rows=warm, comparisons=[], layouts={}, failures=[], cpu=cpu,
        core_rebuilt=False, reused_core_tests=37,
        git_head=subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT, text=True).strip())
    def save():
        atomic_write_json(output / "results.json", report)
    def execute(name, command, timeout=600):
        print("START " + name, flush=True)
        step = run_bounded(command, ROOT, output / "raw" / name, timeout=timeout,
                           memory_gib=4, reserve_gib=24)
        report["steps"].append(step)
        save()
        if step["exit_code"] or step["timed_out"]:
            raise ValueError(name + " failed; raw evidence retained")
        return step
    save()
    try:
        with runtime.reservation(output, runtime.settings(runtime.FRESH_CPU, 1)) as guard:
            report["admission"] = guard
            report["preparation"] = prepare_regraph(source, output / "prepared", 4, 0, "/usr/bin/python3.11")
            execute("build_layout", layout_command(ROOT, output / "prepared", output / "build",
                                                   compiler, xrt_include), 180)
            dependencies = dependency_identities(output / "build/dependencies.d", ROOT)
            report["layout_dependencies"] = dependencies
            pins += [pin(Path(d["path"])) for d in dependencies]
            executable = output / "build/warm_a4"
            execute("build_a4", [str(compiler), "-O3", "-DNDEBUG", "-std=gnu++20", "-Wall",
                "-Wextra", "-Wpedantic", "-Werror", "-I" + str(ROOT / "cpp/include"),
                str(ROOT / "cpp/tests/evaluation_impact/warm_comparison/a4_main.cpp"), "-o", str(executable),
                str(core / "liboriginal_regraph_cycle.a"), str(core / "libspine_cycle_core.a")], 180)
            pins += [pin(executable), pin(output / "build/probe"), pin(output / "harness_sources.tar.gz")]
            for workload in ("smoke", "amazon"):
                source_input = "smoke" if workload == "smoke" else str(reference.parent / "inputs/warm_update")
                exported, layout = output / (workload + "_input"), output / (workload + "_layout")
                exported.mkdir(); layout.mkdir()
                execute(workload + "_export", [str(executable), source_input, str(exported), "export"])
                step = execute(workload + "_layout", [str(output / "build/probe"),
                    str(exported / "graph.txt"), str(layout)])
                report["layouts"][workload] = describe_layout(step, layout, exported / "graph.txt")
                pins += [pin(p) for directory in (exported, layout) for p in sorted(directory.iterdir()) if p.is_file()]
                save()
                for latency in (64, 128):
                    for reverse in (0, 1):
                        name = f"{workload}_lat{latency}_a4_order{reverse}"
                        directory = output / name
                        directory.mkdir()
                        step = execute(name, ["taskset", "-c", str(cpu), str(executable), source_input,
                            str(directory), str(layout), str(latency), str(reverse), "150000000", "run"])
                        row = a4_record(step, directory, workload, latency, reverse)
                        report["rows"].append(row)
                        print("DONE " + name + " " + json.dumps(row["result"]), flush=True)
                        save()
            report["comparisons"] = summarize(report["rows"], warm)
            if any(pin(Path(p["path"])) != p for p in pins):
                raise ValueError("pinned input, core, source or harness changed")
            report["pins_unchanged"] = True
            report["status"] = "COMPLETE_SAME_BATCH_A4_PREDICTION"
            save()
    except Exception as error:
        report["status"] = "FAILED_RETAINED"
        report["failures"].append(repr(error))
        save()
        raise
    return report


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("output", "reference", "comparison", "source", "xrt-include"):
        parser.add_argument("--" + name, type=Path, required=True)
    parser.add_argument("--cpu", type=int, required=True)
    args = parser.parse_args()
    result = run(args.output.resolve(), args.reference.resolve(), args.comparison.resolve(),
                 args.cpu, args.source.resolve(), args.xrt_include.resolve())
    print(json.dumps({"status": result["status"], "comparisons": result["comparisons"]}), flush=True)
