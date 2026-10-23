"""Isolate the current finite input path without changing the numerical core."""

import argparse
import json
import os
from pathlib import Path
import subprocess
import tarfile

from spine_cycle_sim.experiments.campaign_runtime import atomic_write_json, sha256_file
from ...upstream_controls.execution import run_bounded
from ..r_credits.freeze import ROOT, pin
from . import cached_core, input_isolation_analysis as analysis, runtime
from .study import COMPILER


def verify(pins):
    if any(pin(Path(p["path"])) != p for p in pins):
        raise ValueError("frozen artifact changed")


def freeze(output, reference, legacy):
    previous = json.loads(reference.read_text())
    old = json.loads(legacy.read_text())
    if (previous.get("status") != "SSSP_WRAPPER_CONTROL_COMPLETE_SIMULATOR_PREDICTION" or
            previous.get("pins_unchanged") is not True or previous.get("failures") != [] or
            len(previous.get("r_rows", [])) != 12 or
            old.get("status") != "READER_PORTS_COMPLETE_NOT_R_RETENTION" or
            old.get("pins_unchanged") is not True or len(old.get("rows", [])) != 8):
        raise ValueError("complete convergence and historical reader references required")
    external = [p for report in (previous, old) for p in report["pins"]
                if not Path(p["path"]).is_relative_to(ROOT)]
    verify(external)
    output.mkdir(parents=True, exist_ok=False)
    sources = sorted(p for owner in ("cpp", "spine_cycle_sim", "configs", "tests", "scripts", "sst")
                     for p in (ROOT / owner).rglob("*")
                     if p.is_file() and "__pycache__" not in p.parts) + [ROOT / "CMakeLists.txt"]
    with tarfile.open(output / "sources.tar.gz", "w:gz") as archive:
        for source in sources:
            archive.add(source, arcname=source.relative_to(ROOT), recursive=False)
    (output / "pre_edit.diff").write_bytes(subprocess.check_output(
        ["git", "diff", "--binary", "HEAD"], cwd=ROOT))
    result = dict(status="PRE_CURRENT_INPUT_DIAGNOSTIC_FROZEN", reference=pin(reference),
        legacy=pin(legacy), source_pins=[pin(p) for p in sources], external=external,
        artifacts=[pin(output / name) for name in ("sources.tar.gz", "pre_edit.diff")],
        git_head=subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT, text=True).strip(),
        baseline_admitted=False)
    atomic_write_json(output / "freeze.json", result)
    return result


def run(output, before, core_reference, cpu, memory_profile=runtime.CACHED_LOCAL):
    if type(cpu) is not int or cpu not in os.sched_getaffinity(0):
        raise ValueError("one allowed CPU required")
    if memory_profile not in (runtime.CACHED_LOCAL, runtime.CPU_ONLY):
        raise ValueError("checked-core CPU memory profile required")
    selected = runtime.settings(memory_profile, 1)
    frozen = json.loads(before.read_text())
    if frozen.get("status") != "PRE_CURRENT_INPUT_DIAGNOSTIC_FROZEN":
        raise ValueError("pre-edit diagnostic freeze required")
    verify(frozen["artifacts"] + frozen["external"] + [frozen["reference"], frozen["legacy"]])
    core, evidence = cached_core.validate_convergence(ROOT, core_reference, COMPILER)
    legacy = json.loads(Path(frozen["legacy"]["path"]).read_text())
    reference = json.loads(Path(frozen["reference"]["path"]).read_text())
    inputs = core_reference.parent / "inputs/warm_update"
    old_inputs = Path(frozen["legacy"]["path"]).parent / "inputs/warm_update"
    if {p.name: sha256_file(p) for p in inputs.iterdir()} != {
            p.name: sha256_file(p) for p in old_inputs.iterdir()}:
        raise ValueError("legacy and current logical inputs differ")
    output.mkdir(parents=True, exist_ok=False)
    sources = sorted(p for owner in ("cpp", "spine_cycle_sim", "configs", "tests", "scripts", "sst")
                     for p in (ROOT / owner).rglob("*")
                     if p.is_file() and "__pycache__" not in p.parts) + [ROOT / "CMakeLists.txt"]
    with tarfile.open(output / "sources.tar.gz", "w:gz") as archive:
        for source in sources:
            archive.add(source, arcname=source.relative_to(ROOT), recursive=False)
    pins = evidence + [pin(p) for p in sources] + [pin(before), frozen["reference"], frozen["legacy"],
        *frozen["artifacts"], pin(output / "sources.tar.gz")]
    report = dict(status="WAITING_FOR_ADMISSION", steps=[], rows=[], pins=pins, cpu=cpu,
        matrix=analysis.MATRIX, baseline_admitted=False,
        claim="one_scan_finite_input_diagnostic_not_complete_R_or_hardware",
        boundary="resident post-update PMA through drained weighted sinks; no source/compute/G/host",
        core_validation="unchanged checked numerical core; prior 37/37 tests reused, not rerun")

    def save():
        atomic_write_json(output / "results.json", report)

    def checked(label, command):
        print("RUN " + label, flush=True)
        result = run_bounded(command, ROOT, output / "raw" / label,
                             timeout=600, memory_gib=4,
                             reserve_gib=selected["policy"]["reserve_gib"])
        report["steps"].append(result); save()
        if result["exit_code"] or result["timed_out"]:
            raise ValueError("bounded input diagnostic failed: " + label)
        return Path(result["stdout"]).read_text()

    save()
    try:
        with runtime.reservation(output, selected, 120) as safety:
            report.update(status="BUILDING_FRESH_DIAGNOSTIC_HARNESS", safety=safety); save()
            for source in ("prefetch_compact", "prefetch_compact_test"):
                binary = output / source
                checked("build_" + source, cached_core.command(ROOT, core, binary, COMPILER, source))
                pins.append(pin(binary))
            stdout = checked("synthetic", ["taskset", "-c", str(cpu), str(output / "prefetch_compact_test")])
            required = {"PREFETCH_COMPACT_TEST": 16, "DUAL_PORT_PREFETCH_TEST": 16,
                "FULL_BURST_PREFETCH_TEST": 32, "ELASTIC_PREFETCH_TEST": 32,
                "TRIPLE_PORT_PREFETCH_TEST": 16, "DIRECTORY_LOOKAHEAD_TEST": 16,
                "PREFETCH_CAPACITY_TEST": 16}
            if any(f"{name} PASS {count} executions" not in stdout for name, count in required.items()):
                raise ValueError("all finite input tests required")
            report["finite_input_checks"] = required
            verify(pins)
            report["status"] = "RUNNING_CURRENT_INPUT_DIAGNOSTIC"; save()
            for latency, reverse, mode, period in analysis.MATRIX:
                label = f"lat{latency}_reverse{reverse}_{mode}_period{period}"
                command = ["taskset", "-c", str(cpu), str(output / "prefetch_compact"),
                    str(inputs), str(latency), str(reverse), "10000000", str(period)]
                if mode != "single": command.append(mode)
                row = analysis.parse(checked(label, command))
                report["rows"].append(dict(latency=latency, reverse=reverse, mode=mode,
                                           sink_period=period, observations=row))
                save()
            report["analysis"] = analysis.summarize(report["rows"], legacy["rows"], reference["r_rows"])
            verify(pins)
            report.update(status="CURRENT_INPUT_DIAGNOSTIC_COMPLETE_NOT_R_RETENTION", pins_unchanged=True)
    except BaseException as error:
        report.update(status="FAILED_RETAINED", error=repr(error)); raise
    finally:
        save()
    return report


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--freeze", action="store_true")
    for name in ("reference", "legacy", "before", "core-reference"):
        parser.add_argument("--" + name, type=Path)
    parser.add_argument("--cpu", type=int)
    parser.add_argument("--memory-profile", choices=(runtime.CACHED_LOCAL, runtime.CPU_ONLY),
                        default=runtime.CACHED_LOCAL)
    args = parser.parse_args()
    if args.freeze:
        if args.reference is None or args.legacy is None: parser.error("--reference and --legacy required")
        result = freeze(args.output.resolve(), args.reference.resolve(), args.legacy.resolve())
    else:
        if args.before is None or args.core_reference is None or args.cpu is None:
            parser.error("--before, --core-reference and --cpu required")
        result = run(args.output.resolve(), args.before.resolve(), args.core_reference.resolve(),
                     args.cpu, args.memory_profile)
    print(json.dumps({"status": result["status"]}))
