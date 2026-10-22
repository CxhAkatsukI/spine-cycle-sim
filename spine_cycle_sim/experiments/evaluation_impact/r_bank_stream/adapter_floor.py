"""Isolate the production adapter with finite, stall-free diagnostic sinks."""

import argparse
import json
import os
from pathlib import Path
import shutil

from spine_cycle_sim.experiments.campaign_runtime import atomic_write_json, sha256_file
from ...upstream_controls.execution import run_bounded
from ..r_credits.freeze import ROOT, pin
from . import adapter_floor_analysis as analysis, cached_core, runtime
from .analysis import MATRIX, summarize
from .study import COMPILER


def run(output, reference, gates, cpu, admission_wait_seconds=600):
    runtime.wait_budget(admission_wait_seconds)
    if cpu not in os.sched_getaffinity(0):
        raise ValueError("one allowed CPU required")
    baseline = json.loads(reference.read_text())
    if baseline.get("pins_unchanged") is not True or len(baseline["r_rows"]) != len(MATRIX):
        raise ValueError("completed immutable 32-row reference required")
    old = next(p for p in baseline["pins"] if p["path"].endswith("/pre-edit/reference.json"))
    if sha256_file(Path(old["path"])) != old["sha256"]:
        raise ValueError("legacy reference changed")
    accepted = summarize(baseline["r_rows"], json.loads(Path(old["path"]).read_text())["r_rows"])
    if baseline["status"] != accepted["status"] or baseline["analysis"] != accepted:
        raise ValueError("reference acceptance analysis changed")
    inputs = reference.parent / "inputs/warm_update"
    input_pins = {Path(p["path"]).name: p for p in baseline["pins"]
                  if p["path"].startswith(str(inputs) + "/")}
    if set(input_pins) != {p.name for p in inputs.iterdir()} or any(
            sha256_file(inputs / name) != p["sha256"] for name, p in input_pins.items()):
        raise ValueError("reference input missing, unpinned or changed")
    core, pins = cached_core.validate(ROOT, gates)
    output.mkdir(parents=True, exist_ok=False)
    shutil.copytree(inputs, output / "inputs/warm_update")
    sources = sorted(p for owner in ("cpp", "spine_cycle_sim", "configs", "tests", "scripts", "sst")
                     for p in (ROOT / owner).rglob("*") if p.is_file() and "__pycache__" not in p.parts)
    report = dict(status="WAITING_FOR_ADMISSION", cpu=cpu, rows=[], steps=[],
        reference=str(reference), admission_wait_seconds=admission_wait_seconds,
        pins=pins + [pin(reference), pin(COMPILER.resolve()), pin(ROOT / "CMakeLists.txt")] +
             [pin(p) for p in sources] + [pin(p) for p in sorted((output / "inputs/warm_update").iterdir())],
        claim="unchanged_reader_lower_bound_not_R_or_hardware_performance")

    def save():
        atomic_write_json(output / "results.json", report)

    def check_pins():
        if any(sha256_file(Path(p["path"])) != p["sha256"] for p in report["pins"]):
            raise ValueError("pinned source/input/library/compiler/reference changed")

    save()
    try:
        with runtime.reservation(output, runtime.settings(runtime.CPU_ONLY, 1), admission_wait_seconds) as safety:
            report.update(status="BUILDING_FRESH_HARNESS", safety=safety)
            (output / "build").mkdir()
            binary = output / "build/adapter_floor"
            step = run_bounded(cached_core.command(ROOT, core, binary, COMPILER, "adapter_floor"), ROOT,
                output / "raw/build", timeout=600, memory_gib=4, reserve_gib=8)
            report["steps"].append(step)
            save()
            if step["exit_code"] or step["timed_out"]:
                raise ValueError("floor harness build failed")
            report["pins"].append(pin(binary))
            check_pins()
            report["status"] = "RUNNING_FINITE_ADAPTER_DIAGNOSTIC"
            save()
            for latency in (64, 128):
                for reverse in (0, 1):
                    label = f"lat{latency}_reverse{reverse}"
                    print("RUN " + label, flush=True)
                    command = ["taskset", "-c", str(cpu), str(binary), str(output / "inputs/warm_update"),
                               str(latency), str(reverse), "100000000"]
                    step = run_bounded(command, ROOT, output / "raw" / label,
                        timeout=600, memory_gib=4, reserve_gib=8)
                    report["steps"].append(step)
                    save()
                    if step["exit_code"] or step["timed_out"]:
                        raise ValueError("floor diagnostic failed: " + label)
                    row = analysis.parse(Path(step["stdout"]).read_text())
                    report["rows"].append(dict(latency=latency, reverse=reverse, observations=row))
                    save()
                    print("DONE " + label + " PASS", flush=True)
            report["analysis"] = analysis.summarize(report["rows"], baseline["r_rows"])
            check_pins()
            report.update(status="ADAPTER_FLOOR_DIAGNOSTIC_COMPLETE_NOT_RETENTION", pins_unchanged=True)
    except runtime.AdmissionUnavailable as error:
        report.update(status="ADMISSION_NOT_GRANTED_NO_EXECUTION", error=repr(error))
        save()
        raise
    except BaseException as error:
        report.update(status="FAILED_RETAINED", error=repr(error))
        save()
        raise
    save()
    return report


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--reference", type=Path, required=True)
    parser.add_argument("--core-gates", type=Path, required=True)
    parser.add_argument("--cpu", type=int, required=True)
    parser.add_argument("--admission-wait-seconds", type=int, default=600)
    args = parser.parse_args()
    result = run(args.output.resolve(), args.reference.resolve(), args.core_gates.resolve(),
                 args.cpu, args.admission_wait_seconds)
    print(json.dumps({"status": result["status"], "analysis": result["analysis"]}))
