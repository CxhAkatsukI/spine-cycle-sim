"""Replay four accepted R predictions with read-only completion records."""

import argparse
from concurrent.futures import ProcessPoolExecutor, as_completed
import json
import multiprocessing
import os
from pathlib import Path
import shutil

from spine_cycle_sim.experiments.campaign_runtime import atomic_write_json, sha256_file
from ...upstream_controls.execution import run_bounded
from ..r_execution import run_case
from ..r_credits.freeze import ROOT, pin
from . import cached_core, progress, runtime
from .analysis import MATRIX, identity, summarize
from .study import COMPILER


CASES = [(lat, reverse, "bank_stream") for lat in (64, 128) for reverse in (0, 1)]


def run(output, reference, gates, cpus, admission_wait_seconds=600):
    runtime.wait_budget(admission_wait_seconds)
    if len(cpus) != 4 or len(set(cpus)) != 4 or not set(cpus) <= os.sched_getaffinity(0):
        raise ValueError("four distinct allowed CPUs required")
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
    report = {"status": "WAITING_FOR_ADMISSION", "cases": CASES, "r_rows": [], "failures": [], "steps": [],
        "cpus": cpus, "reference": str(reference), "admission_wait_seconds": admission_wait_seconds,
        "progress": [], "pins": pins + [pin(reference),
            pin(COMPILER.resolve()), pin(ROOT / "CMakeLists.txt")] + [pin(p) for p in sources] +
            [pin(p) for p in sorted((output / "inputs/warm_update").iterdir())],
        "claim": "read_only_simulator_completion_diagnostic_not_optimization_or_hardware"}

    def save():
        atomic_write_json(output / "results.json", report)

    def check_pins():
        if any(sha256_file(Path(p["path"])) != p["sha256"] for p in report["pins"]):
            raise ValueError("pinned source/input/library/compiler/reference changed")

    save()
    try:
        with runtime.reservation(output, runtime.settings(runtime.CPU_ONLY, 4), admission_wait_seconds) as safety:
            report.update(status="BUILDING_FRESH_HARNESS", safety=safety)
            (output / "build").mkdir()
            binary = output / "build/regraph_convergence_demo"
            step = run_bounded(cached_core.command(ROOT, core, binary, COMPILER, "convergence"), ROOT,
                output / "raw/build", timeout=600, memory_gib=4, reserve_gib=8)
            report["steps"].append(step)
            save()
            if step["exit_code"] or step["timed_out"]:
                raise ValueError("diagnostic harness build failed")
            report["pins"].append(pin(binary))
            check_pins()
            report["status"] = "RUNNING_READ_ONLY_REPLAY"
            save()
            with ProcessPoolExecutor(max_workers=4, mp_context=multiprocessing.get_context("spawn")) as pool:
                futures = {pool.submit(run_case, ROOT, output, binary, cpus[i], 1_500_000_000, 1800, case, 8,
                    output / "progress" / f"lat{case[0]}_reverse{case[1]}"): case
                    for i, case in enumerate(CASES)}
                for future in as_completed(futures):
                    result = future.result()
                    case = futures[future]
                    report["steps"].append(result["step"])
                    if "row" not in result:
                        report["failures"].append(result)
                    else:
                        row = result["row"]
                        expected = next(r for r in baseline["r_rows"] if identity(r) == case)
                        if any(row[k] != expected[k] for k in ("observations", "outputs")):
                            raise ValueError("read-only instrumentation changed numerical result")
                        directory = output / "progress" / f"lat{case[0]}_reverse{case[1]}"
                        detail = progress.load(directory, row["observations"], 4)
                        report["pins"] += [pin(p) for p in sorted(directory.iterdir())]
                        report["r_rows"].append(row)
                        report["progress"].append({"latency": case[0], "reverse": case[1], **detail})
                    save()
            if report["failures"] or len(report["r_rows"]) != 4:
                raise ValueError("incomplete progress replay")
            report["progress"].sort(key=lambda row: (row["latency"], row["reverse"]))
            for latency in (64, 128):
                pair = [r for r in report["progress"] if r["latency"] == latency]
                if any(pair[0][key] != pair[1][key] for key in ("rounds", "invocations", "analysis")):
                    raise ValueError("registration order changed progress records")
            check_pins()
            report.update(status="READ_ONLY_PROGRESS_REPLAY_EXACT", pins_unchanged=True,
                          numerical_replays_exact=4)
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
    parser.add_argument("--cpus", type=int, nargs=4, required=True)
    parser.add_argument("--admission-wait-seconds", type=int, default=600)
    args = parser.parse_args()
    print(json.dumps({"status": run(args.output.resolve(), args.reference.resolve(),
                                   args.core_gates.resolve(), tuple(args.cpus), args.admission_wait_seconds)["status"]}))
