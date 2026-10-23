"""Fresh core, legacy replay and explicit finite compact-input convergence."""

import argparse
from concurrent.futures import ProcessPoolExecutor, as_completed
import json
import multiprocessing
import os
from pathlib import Path
import shutil
import tarfile

from spine_cycle_sim.experiments.campaign_runtime import atomic_write_json, sha256_file
from ...upstream_controls.execution import run_bounded
from ..r_credits.freeze import ROOT, pin
from ..r_execution import run_case
from .compact_analysis import MATRIX, summarize
from .runtime import CACHED_LOCAL, FRESH_CPU, LOCAL, LOCAL_PARALLEL, reservation, settings
from .study import COMPILER, configure_command
from . import cached_core

def validate_cpus(cpus):
    if (not 1 <= len(cpus) <= 4 or len(set(cpus)) != len(cpus) or
            any(type(cpu) is not int or cpu not in os.sched_getaffinity(0) for cpu in cpus)):
        raise ValueError("one to four distinct allowed CPUs required")


def execution_profile(cached, cpus, memory_profile):
    if memory_profile not in (None, CACHED_LOCAL, FRESH_CPU):
        raise ValueError("unsupported convergence memory profile override")
    if memory_profile == CACHED_LOCAL and cached is None:
        raise ValueError("small cached profile requires an exactly validated core")
    if memory_profile == FRESH_CPU and cached is not None:
        raise ValueError("fresh CPU profile requires a fresh numerical core build")
    return settings(memory_profile or (LOCAL if len(cpus) == 1 else LOCAL_PARALLEL), len(cpus))


def run(output, reference_path, cpus, *, matrix=MATRIX, analyze=summarize,
        extra_references=(), complete_status="COMPACT_CONVERGENCE_COMPLETE_NOT_HARDWARE_ADMISSION",
        prefetch_checks=False, extra_input_checks=None, cached_reference=None, memory_profile=None):
    validate_cpus(cpus)
    reference = json.loads(reference_path.read_text())
    cached = None
    if cached_reference is not None:
        if cached_reference != reference_path:
            raise ValueError("cached core and complete convergence reference must be identical")
        cached = cached_core.validate_convergence(ROOT, cached_reference, COMPILER)
    elif reference.get("pins_unchanged") is not True or len(reference.get("r_rows", [])) != 32:
        raise ValueError("checked complete bank-stream reference required")
    selected_memory = execution_profile(cached, cpus, memory_profile)
    output.mkdir(parents=True, exist_ok=False)
    shutil.copytree(reference_path.parent / "inputs/warm_update", output / "inputs/warm_update")
    sources = sorted(path for owner in ("cpp", "spine_cycle_sim", "configs", "tests", "scripts", "sst")
                     for path in (ROOT / owner).rglob("*")
                     if path.is_file() and "__pycache__" not in path.parts)
    sources.append(ROOT / "CMakeLists.txt")
    with tarfile.open(output / "sources.tar.gz", "w:gz") as archive:
        for path in sources:
            archive.add(path, arcname=path.relative_to(ROOT), recursive=False)
    report = {"status": "WAITING_FOR_ADMISSION", "matrix": matrix, "steps": [], "r_rows": [],
              "failures": [], "cpus": cpus, "maximum_cycles": 1_500_000_000,
              "boundary": "resident warm weighted SSSP compute to convergence; no G/host/DMA",
              "claim": "experimental_finite_input_simulator_prediction_not_hardware",
              "pins": [pin(path) for path in sources] + [pin(COMPILER.resolve()), pin(reference_path),
                  pin(output / "sources.tar.gz")] + [pin(path) for path in extra_references] +
                  [pin(path) for path in sorted((output / "inputs/warm_update").iterdir())]}

    def save():
        atomic_write_json(output / "results.json", report)

    def verify():
        if any(sha256_file(Path(p["path"])) != p["sha256"] for p in report["pins"]):
            raise ValueError("frozen source, compiler, input or artifact changed")

    def checked(command, label, timeout=1800):
        print("RUN " + label, flush=True)
        step = run_bounded(command, ROOT, output / "raw" / label, timeout=timeout,
                           memory_gib=4, reserve_gib=24)
        report["steps"].append(step); save()
        if step["exit_code"] or step["timed_out"]:
            raise ValueError("bounded check failed: " + label)
        return Path(step["stdout"]).read_text()

    save()
    try:
        with reservation(output, selected_memory, 600) as safety:
            report.update(status="BUILDING_CHECKED_CORE_HARNESS" if cached else "BUILDING_FRESH_CORE",
                          safety=safety); save()
            build = output / "build"
            if cached:
                core, evidence = cached
                build.mkdir()
                report["pins"] += evidence
                report["core_validation"] = "unchanged numerical core; reused prior 37/37 tests, not rerun"
                for source, target in (("convergence", "regraph_convergence_demo"),
                                       ("credit_control_test", "regraph_credit_control_test")):
                    checked(cached_core.command(ROOT, core, build / target, COMPILER, source),
                            "build_" + source)
            else:
                checked(configure_command(build), "configure")
                # EXCLUDE_FROM_ALL in the experiment project requires an explicit core build.
                checked(["cmake", "--build", str(build), "--target", "regraph_convergence_demo",
                         "regraph_credit_control_test", "-j1"], "build_harness")
                checked(["cmake", "--build", str(build / "simulator"), "-j1"], "build_core")
                checked(["ctest", "--test-dir", str(build / "simulator"), "--output-on-failure",
                         "--timeout", "600", "-j1"], "core_ctest", 2400)
            checked([str(build / "regraph_credit_control_test")], "control_test", 30)
            if prefetch_checks:
                binary = build / "prefetch_compact_test"
                checked(cached_core.command(ROOT, core if cached else build / "simulator/cpp", binary, COMPILER,
                                            "prefetch_compact_test"), "build_input_tests")
                stdout = checked(["taskset", "-c", str(cpus[0]), str(binary)], "input_tests", 120)
                required = {"PREFETCH_COMPACT_TEST": 16, "DUAL_PORT_PREFETCH_TEST": 16,
                            "FULL_BURST_PREFETCH_TEST": 32, "ELASTIC_PREFETCH_TEST": 32,
                            "TRIPLE_PORT_PREFETCH_TEST": 16, "DIRECTORY_LOOKAHEAD_TEST": 16}
                required.update(extra_input_checks or {})
                if any(f"{name} PASS {count} executions" not in stdout for name, count in required.items()):
                    raise ValueError("all declared finite input executions required")
                report["finite_input_checks"] = required
                report["input_probes"] = [json.loads(line.partition(" ")[2]) for line in stdout.splitlines()
                                          if line.startswith("PIPELINE_PROBE ")]
                if len(report["input_probes"]) != 4:
                    raise ValueError("all four publisher storage/backpressure probes required")
                report["pins"].append(pin(binary))
            names = ("regraph_convergence_demo", "regraph_credit_control_test") if cached else (
                "CMakeCache.txt", "compile_commands.json", "regraph_convergence_demo",
                "regraph_credit_control_test", "simulator/cpp/libspine_cycle_core.a",
                "simulator/cpp/liboriginal_regraph_cycle.a")
            report["pins"] += [pin(build / name) for name in names]
            verify()
            report["status"] = "RUNNING_COMPLETE_CONVERGENCE_MATRIX"; save()
            with ProcessPoolExecutor(max_workers=len(cpus),
                    mp_context=multiprocessing.get_context("spawn")) as pool:
                futures = []
                for index, case in enumerate(matrix):
                    verify()
                    progress = (output / "progress" / f"lat{case[0]}_reverse{case[1]}_{case[2]}"
                                if case[2] != "a4_io16" else None)
                    futures.append(pool.submit(run_case, ROOT, output, build / "regraph_convergence_demo",
                        cpus[index % len(cpus)], report["maximum_cycles"], 1800, case, 24, progress))
                for future in as_completed(futures):
                    result = future.result()
                    report["steps"].append(result["step"])
                    if "row" in result: report["r_rows"].append(result["row"])
                    else: report["failures"].append(result)
                    save()
            report["r_rows"].sort(key=lambda row: matrix.index((row["latency"], row["reverse"], row["arm"])))
            if report["failures"]:
                raise ValueError("matrix contains retained failures")
            report["analysis"] = analyze(report["r_rows"], reference["r_rows"])
            report["progress"] = [pin(path) for path in sorted((output / "progress").rglob("*.csv"))]
            verify()
            report.update(status=complete_status, pins_unchanged=True)
    except BaseException as error:
        report.update(status="FAILED_RETAINED", error=repr(error)); save()
        raise
    save()
    return report


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--reference", type=Path, required=True)
    affinity = parser.add_mutually_exclusive_group(required=True)
    affinity.add_argument("--cpu", type=int)
    affinity.add_argument("--cpus", type=int, nargs="+")
    args = parser.parse_args()
    print(json.dumps({"status": run(args.output.resolve(), args.reference.resolve(),
                                  args.cpus if args.cpus is not None else [args.cpu])["status"]}))
