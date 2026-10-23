"""Replay the twelve frozen SSSP trajectories against freshly built core code."""

import argparse
import json
from pathlib import Path
import subprocess

from spine_cycle_sim.experiments.campaign_runtime import atomic_write_json
from ....upstream_controls.execution import run_bounded
from ...r_bank_stream import runtime
from ...r_credits.freeze import ROOT, pin
from ...warm_comparison.analysis import record, summarize
from ..delivery import equivalence
from . import sssp_replay


def run(output, core, before, input_root, cpu, allow_read_credit_correction=False):
    output.mkdir(parents=True, exist_ok=False)
    (output / "build").mkdir()
    sources = [p for p in (ROOT / "cpp/tests/evaluation_impact").rglob("*")
               if p.is_file() and p.suffix in (".hpp", ".cpp")]
    libraries = [core / "cpp" / name for name in ("liboriginal_regraph_cycle.a", "libspine_cycle_core.a")]
    report = dict(status="RUNNING", pins=[pin(p) for p in sources + libraries] + [pin(before)],
                  rows=[], failures=[], steps=[])
    def save():
        atomic_write_json(output / "results.json", report)
    def execute(command, name, timeout):
        result = run_bounded(command, ROOT, output / "raw" / name, timeout=timeout, memory_gib=4, reserve_gib=24)
        report["steps"].append(result)
        save()
        return result
    save()
    try:
        with runtime.reservation(output, runtime.settings(runtime.FRESH_CPU, 1)) as guard:
            report["admission"] = guard
            binary = output / "build/warm_comparison"
            result = execute(["/usr/bin/g++", "-std=gnu++20", "-O3", "-DNDEBUG", "-Wall", "-Wextra",
                "-Wpedantic", "-Werror", "-I" + str(ROOT / "cpp/include"),
                str(ROOT / "cpp/tests/evaluation_impact/warm_comparison/main.cpp"),
                *map(str, libraries), "-o", str(binary)], "build", 240)
            if result["exit_code"] or result["timed_out"]:
                raise ValueError("regression harness compilation failed")
            report["pins"].append(pin(binary))
            for workload in ("smoke", "amazon"):
                for latency in (64, 128):
                    for arm, reverse in (("gr", 0), ("gr", 1), ("spine", 0)):
                        name = f"{workload}_lat{latency}_{arm}_order{reverse}"
                        directory = output / name
                        directory.mkdir()
                        source = "smoke" if workload == "smoke" else str(input_root)
                        print("START " + name, flush=True)
                        result = execute(["taskset", "-c", str(cpu), str(binary), source,
                            str(directory), str(latency), str(reverse), "150000000", arm], name, 600)
                        report["rows"].append(record(result, directory, workload, latency, arm, reverse))
                        print("DONE " + name, flush=True)
                        save()
            report["comparisons"] = summarize(report["rows"])
            if any(pin(Path(p["path"])) != p for p in report["pins"]):
                raise ValueError("regression dependency changed")
            report["pins_unchanged"] = True
            save()
            if allow_read_credit_correction:
                checked = sssp_replay.compare(json.loads(before.read_text()), report)
                checked.update(before=dict(path=str(before), sha256=pin(before)["sha256"]),
                    after=dict(path=str(output / "results.json")))
                report["equivalence"] = checked
                report["status"] = checked["status"]
            else:
                report["equivalence"] = equivalence(before, output / "results.json")
                report["status"] = "EXACT_SSSP_STATE_CYCLE_TRAFFIC_REPLAY"
            save()
    except Exception as error:
        report["status"] = "FAILED_RETAINED"
        report["failures"].append(repr(error))
        save()
        raise
    return report


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("output", "core", "before", "input-root"):
        parser.add_argument("--" + name, type=Path, required=True)
    parser.add_argument("--cpu", type=int, required=True)
    parser.add_argument("--allow-read-credit-correction", action="store_true")
    args = parser.parse_args()
    print(json.dumps(dict(status=run(args.output.resolve(), args.core.resolve(), args.before.resolve(),
        args.input_root.resolve(), args.cpu, args.allow_read_credit_correction)["status"])))
