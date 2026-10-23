"""Replay a frozen first round with passive per-cycle wait observations."""

import argparse
import json
import os
from pathlib import Path
import subprocess
import tarfile

from spine_cycle_sim.experiments.campaign_runtime import atomic_write_json, sha256_file
from ...upstream_controls.execution import run_bounded
from ..r_credits.freeze import ROOT, pin
from . import progress, runtime, wait_overlap_analysis

ARMS = ("prefetch_ready_fullburst", "prefetch_ready_capacity512")


def run(output, reference, cpu, admission_wait_seconds=600):
    runtime.wait_budget(admission_wait_seconds)
    if cpu not in os.sched_getaffinity(0):
        raise ValueError("CPU is outside allowed affinity")
    baseline = json.loads(reference.read_text())
    if (baseline.get("status") != "PREFETCH_CAPACITY_COMPLETE_SIMULATOR_PREDICTION" or
            baseline.get("pins_unchanged") is not True or len(baseline["r_rows"]) != 12):
        raise ValueError("completed twelve-row capacity reference required")
    pins = baseline["pins"] + [pin(reference)]
    sources = sorted((ROOT / "cpp/tests/evaluation_impact/wait_overlap").glob("*")) + [
        Path(__file__).resolve(), Path(wait_overlap_analysis.__file__).resolve(),
        ROOT / "tests/test_regraph_wait_overlap.py"]
    pins += [pin(p) for p in sources]

    def check_pins():
        if any(sha256_file(Path(p["path"])) != p["sha256"] for p in pins):
            raise ValueError("source, library, compiler, input or reference changed")

    check_pins()
    output.mkdir(parents=True, exist_ok=False)
    report = dict(status="WAITING_FOR_ADMISSION", pins=pins, rows=[], steps=[],
        cpu=cpu, reference=str(reference), baseline_admitted=False,
        claim="passive_first_round_simulator_diagnostic_not_complete_convergence_or_hardware")
    with tarfile.open(output / "sources.tar.gz", "w:gz") as archive:
        for source in sources:
            archive.add(source, arcname=str(source.relative_to(ROOT)))
    pins.append(pin(output / "sources.tar.gz"))
    report["git_head"] = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT, text=True).strip()
    inputs = reference.parent / "inputs/warm_update"
    command = list(next(s["command"] for s in baseline["steps"] if s["command"][0] == "/usr/bin/g++"))
    command[command.index("-o") - 1] = str(ROOT / "cpp/tests/evaluation_impact/wait_overlap/round_probe.cpp")
    binary = output / "wait_probe"
    command[command.index("-o") + 1] = str(binary)

    def save():
        atomic_write_json(output / "results.json", report)

    def step(name, arguments):
        result = run_bounded(arguments, ROOT, output / "raw" / name,
                             timeout=600, memory_gib=2, reserve_gib=24)
        report["steps"].append(result)
        save()
        if result["exit_code"] or result["timed_out"]:
            raise ValueError("diagnostic step failed: " + name)
        return result

    save()
    try:
        with runtime.reservation(output, runtime.settings(runtime.LOCAL, 1), admission_wait_seconds) as safety:
            report.update(status="BUILDING_FRESH_PROBE", safety=safety)
            step("build", command)
            pins.append(pin(binary))
            for latency in (64, 128):
                for arm in ARMS:
                    for reverse in (0, 1):
                        before = next(row for row in baseline["r_rows"] if
                            (row["latency"], row["arm"], row["reverse"]) == (latency, arm, reverse))
                        old_progress = reference.parent / "progress" / f"lat{latency}_reverse{reverse}_{arm}"
                        pair = []
                        for sample in (0, 1):
                            name = f"lat{latency}_{arm}_reverse{reverse}_sample{sample}"
                            directory = output / "outputs" / name
                            directory.mkdir(parents=True)
                            report.update(status="RUNNING_PASSIVE_REPLAY", running_case=name)
                            result = step(name, ["taskset", "-c", str(cpu), str(binary), str(inputs),
                                                str(directory), str(latency), str(reverse), arm, str(sample)])
                            records = [json.loads(line.split(" ", 1)[1]) for line in Path(result["stdout"]).read_text().splitlines()
                                       if line.startswith("WAIT_RESULT ")]
                            if len(records) != 1 or records[0].get("passed") is not True:
                                raise ValueError("missing correctness/conservation result")
                            value = records[0]
                            trajectory = before["observations"]["trajectory"][0]
                            if value["cycles"] != trajectory["cycles"] or value["active"] != trajectory["active"]:
                                raise ValueError("diagnostic differs from complete reference first round")
                            rounds = progress.read(directory / "rounds.csv", progress.ROUND_FIELDS)
                            invocations = progress.read(directory / "invocations.csv", progress.INVOCATION_FIELDS)
                            if rounds != progress.read(old_progress / "rounds.csv", progress.ROUND_FIELDS)[:1] or invocations != [
                                    row for row in progress.read(old_progress / "invocations.csv", progress.INVOCATION_FIELDS)
                                    if row["round"] == 0]:
                                raise ValueError("passive replay changed completion endpoints")
                            artifacts = [dict(name=p.name, sha256=sha256_file(p)) for p in sorted(directory.iterdir())
                                         if p.name != "wait_overlap.csv"]
                            pair.append((value, artifacts))
                            row = dict(latency=latency, arm=arm, reverse=reverse, sample=sample,
                                       result=value, outputs=artifacts, directory=str(directory))
                            if sample:
                                row["overlap"] = wait_overlap_analysis.summarize(directory, value["cycles"])
                            report["rows"].append(row)
                            pins.extend(pin(p) for p in sorted(directory.iterdir()))
                            save()
                        if pair[0] != pair[1]:
                            raise ValueError("observation changed result, traffic or output files")
            for latency in (64, 128):
                for arm in ARMS:
                    pair = [r for r in report["rows"] if r["latency"] == latency and r["arm"] == arm and r["sample"]]
                    if pair[0]["overlap"] != pair[1]["overlap"] or pair[0]["outputs"] != pair[1]["outputs"]:
                        raise ValueError("registration order changed passive histogram or outputs")
            check_pins()
            report.update(status="PASS_READ_ONLY_WAIT_OVERLAP", pins_unchanged=True,
                          exact_instrumentation_pairs=8, exact_reference_first_rounds=16)
    except BaseException as error:
        report.update(status="FAILED_RETAINED", error=repr(error))
        raise
    finally:
        save()
    return report


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--reference", type=Path, required=True)
    parser.add_argument("--cpu", type=int, required=True)
    parser.add_argument("--admission-wait-seconds", type=int, default=600)
    args = parser.parse_args()
    result = run(args.output.resolve(), args.reference.resolve(), args.cpu, args.admission_wait_seconds)
    print(json.dumps({key: result[key] for key in ("status", "exact_instrumentation_pairs", "exact_reference_first_rounds")}))
