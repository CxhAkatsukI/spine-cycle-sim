"""Fresh Release build, exact 28-row replay, then four current-topology rows."""

import argparse
from concurrent.futures import ProcessPoolExecutor, as_completed
import json
import multiprocessing
import os
from pathlib import Path
import shutil

from spine_cycle_sim.experiments.campaign_runtime import atomic_write_json, sha256_file
from ...upstream_controls.execution import run_bounded
from ..r_credits.freeze import ROOT, pin
from ..r_credits.study import REGRESSION_TARGETS
from ..r_execution import run_case
from .analysis import MATRIX, identity, summarize
from .runtime import AdmissionUnavailable, CPU_ONLY, PROFILES, memory_profiles, reservation, settings, wait_budget
from . import cached_core


COMPILER = Path("/usr/bin/g++")
REGRESSION_TIMEOUT_SECONDS = 600


def configure_command(build):
    return ["cmake", "-S", str(ROOT / "cpp/tests/evaluation_impact"), "-B", str(build),
            "-DCMAKE_CXX_COMPILER=" + str(COMPILER), "-DCMAKE_BUILD_TYPE=Release",
            "-DCMAKE_EXPORT_COMPILE_COMMANDS=ON", "-DBUILD_TESTING=ON"]


def run(output, before, inputs, cpus, memory_profile=memory_profiles.SEELE, admission_wait_seconds=600,
        core_gates=None):
    wait_budget(admission_wait_seconds)
    selected = settings(memory_profile, len(cpus))
    if selected["profile"] == CPU_ONLY and core_gates is None:
        raise ValueError("CPU-only mode requires an already checked numerical core")
    core, cached_pins = cached_core.validate(ROOT, core_gates) if core_gates else (None, [])
    reserve_gib = selected["policy"]["reserve_gib"]
    freeze = json.loads((before / "freeze.json").read_text())
    if freeze["status"] != "PRE_EDIT_FROZEN" or any(
            sha256_file(before / name) != freeze[key] for name, key in (
                ("source.tar.gz", "sources_sha256"), ("reference.json", "reference_sha256"))):
        raise ValueError("pre-edit source/reference freeze changed")
    reference = json.loads((before / "reference.json").read_text())["r_rows"]
    for frozen in freeze["pins"]:
        if "/inputs/warm_update/" in frozen["path"] and (
                sha256_file(inputs / Path(frozen["path"]).name) != frozen["sha256"]):
            raise ValueError("relocated input differs from pre-edit freeze")
    if not cpus or len(cpus) > 4 or len(set(cpus)) != len(cpus) or not set(cpus) <= os.sched_getaffinity(0):
        raise ValueError("one to four distinct allowed CPU cores required")
    output.mkdir(parents=True, exist_ok=False)
    shutil.copytree(inputs, output / "inputs/warm_update")
    sources = sorted(p for owner in ("cpp", "spine_cycle_sim", "configs", "tests", "scripts", "sst")
                     for p in (ROOT / owner).rglob("*")
                     if p.is_file() and "__pycache__" not in p.parts)
    sources.append(ROOT / "CMakeLists.txt")
    report = {"status": "WAITING_FOR_ADMISSION", "matrix": MATRIX, "r_rows": [], "failures": [],
        "steps": [], "cpus": cpus, "execution_profile": selected, "admission_wait_seconds": admission_wait_seconds,
        "build_mode": "checked_cached_core_fresh_harness" if core_gates else "fresh_complete_core",
        "maximum_cycles": 1_500_000_000, "case_timeout_seconds": 1800,
        "regression_timeout_seconds": REGRESSION_TIMEOUT_SECONDS,
        "pins": cached_pins + [pin(p) for p in sources] + [pin(COMPILER.resolve())] + [pin(before / name) for name in
            ("freeze.json", "source.tar.gz", "reference.json")] +
            [pin(p) for p in sorted((output / "inputs/warm_update").iterdir())],
        "boundary": "same resident warm weighted SSSP compute to convergence; no G/host/DMA",
        "legacy_source_masters": 4, "bank_stream_source_masters": 2,
        "claim": "compute_prediction_not_FPGA_or_publication"}

    def save():
        atomic_write_json(output / "results.json", report)

    def checked(command, label, timeout=1200):
        print("RUN " + label, flush=True)
        step = run_bounded(command, ROOT, output / "raw" / label,
                           timeout=timeout, memory_gib=4, reserve_gib=reserve_gib)
        report["steps"].append(step)
        save()
        if step["exit_code"] or step["timed_out"]:
            raise RuntimeError("bounded build/check failed: " + label)

    def verify_pins():
        if any(sha256_file(Path(p["path"])) != p["sha256"] for p in report["pins"]):
            raise ValueError("pinned source/input/build changed")

    save()
    try:
        with reservation(output, selected, admission_wait_seconds) as safety:
            report.update(status="BUILDING", safety=safety)
            save()
            build = output / "build"
            checked([str(COMPILER), "--version"], "compiler", 30)
            if core_gates:
                build.mkdir()
                for source, target in (("convergence", "regraph_convergence_demo"),
                                       ("credit_control_test", "regraph_credit_control_test")):
                    checked(cached_core.command(ROOT, core, build / target, COMPILER, source), "build_" + source)
                regression_root = core.parent
                report["pins"] += [pin(core / name) for name in REGRESSION_TARGETS]
            else:
                checked(configure_command(build), "configure")
                cache = dict(line.split("=", 1) for line in (build / "CMakeCache.txt").read_text().splitlines()
                             if line.startswith("CMAKE_CXX_COMPILER:"))
                if len(cache) != 1 or Path(next(iter(cache.values()))).resolve() != COMPILER.resolve():
                    raise ValueError("CMake did not select the pinned GCC compiler")
                checked(["cmake", "--build", str(build), "--target", "regraph_convergence_demo",
                    "regraph_credit_control_test", *REGRESSION_TARGETS, "-j1"], "build", 1800)
                regression_root = build / "simulator"
                report["pins"] += [pin(build / name) for name in ("CMakeCache.txt", "compile_commands.json",
                    "simulator/cpp/libspine_cycle_core.a", "simulator/cpp/liboriginal_regraph_cycle.a")]
                report["pins"] += [pin(build / "simulator/cpp" / name) for name in REGRESSION_TARGETS]
            checked([str(build / "regraph_credit_control_test")], "control_test", 30)
            checked(["ctest", "--test-dir", str(regression_root), "--output-on-failure", "--timeout",
                str(REGRESSION_TIMEOUT_SECONDS),
                "-j1", "-R", "^(" + "|".join(REGRESSION_TARGETS) + ")$"], "regression")
            report["pins"] += [pin(build / name) for name in ("regraph_convergence_demo", "regraph_credit_control_test")]
            verify_pins()
            report["status"] = "RUNNING_PREDECLARED_MATRIX"
            save()
            with ProcessPoolExecutor(max_workers=len(cpus), mp_context=multiprocessing.get_context("spawn")) as pool:
                priority = {arm: i for i, arm in enumerate(("bank_stream", "a4_io16", "a4", "candidate"))}
                prioritized = sorted(MATRIX, key=lambda row: priority.get(row[2], 4))
                futures = [pool.submit(run_case, ROOT, output, build / "regraph_convergence_demo",
                    cpus[i % len(cpus)], report["maximum_cycles"], report["case_timeout_seconds"], case, reserve_gib)
                    for i, case in enumerate(prioritized)]
                for future in as_completed(futures):
                    result = future.result()
                    report["steps"].append(result["step"])
                    if "row" in result:
                        report["r_rows"].append(result["row"])
                    else:
                        report["failures"].append(result)
                    save()
            if report["failures"]:
                raise ValueError("matrix contains retained failures")
            report["r_rows"].sort(key=lambda row: MATRIX.index(identity(row)))
            report["analysis"] = summarize(report["r_rows"], reference)
            verify_pins()
            report.update(status=report["analysis"]["status"], pins_unchanged=True)
    except AdmissionUnavailable as error:
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
    parser.add_argument("--before", type=Path, required=True)
    parser.add_argument("--inputs", type=Path, required=True)
    parser.add_argument("--cpus", type=int, nargs="+", required=True)
    parser.add_argument("--memory-profile", choices=PROFILES, default=memory_profiles.SEELE)
    parser.add_argument("--admission-wait-seconds", type=int, default=600)
    parser.add_argument("--core-gates", type=Path, help="reuse this checked core; freshly compile only the harness")
    args = parser.parse_args()
    print(json.dumps({"status": run(args.output.resolve(), args.before.resolve(),
                                   args.inputs.resolve(), tuple(args.cpus), args.memory_profile,
                                   args.admission_wait_seconds, args.core_gates)["status"]}))
