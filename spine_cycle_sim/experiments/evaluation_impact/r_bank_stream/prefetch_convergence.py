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
from .runtime import LOCAL, LOCAL_PARALLEL, reservation, settings
from .study import COMPILER, configure_command

def validate_cpus(cpus):
    if (not 1 <= len(cpus) <= 4 or len(set(cpus)) != len(cpus) or
            any(type(cpu) is not int or cpu not in os.sched_getaffinity(0) for cpu in cpus)):
        raise ValueError("one to four distinct allowed CPUs required")


def run(output, reference_path, cpus):
    validate_cpus(cpus)
    reference = json.loads(reference_path.read_text())
    if reference.get("pins_unchanged") is not True or len(reference.get("r_rows", [])) != 32:
        raise ValueError("checked complete bank-stream reference required")
    output.mkdir(parents=True, exist_ok=False)
    shutil.copytree(reference_path.parent / "inputs/warm_update", output / "inputs/warm_update")
    sources = sorted(path for owner in ("cpp", "spine_cycle_sim", "configs", "tests", "scripts", "sst")
                     for path in (ROOT / owner).rglob("*")
                     if path.is_file() and "__pycache__" not in path.parts)
    sources.append(ROOT / "CMakeLists.txt")
    with tarfile.open(output / "sources.tar.gz", "w:gz") as archive:
        for path in sources:
            archive.add(path, arcname=path.relative_to(ROOT), recursive=False)
    report = {"status": "WAITING_FOR_ADMISSION", "matrix": MATRIX, "steps": [], "r_rows": [],
              "failures": [], "cpus": cpus, "maximum_cycles": 1_500_000_000,
              "boundary": "resident warm weighted SSSP compute to convergence; no G/host/DMA",
              "claim": "experimental_finite_input_simulator_prediction_not_hardware",
              "pins": [pin(path) for path in sources] + [pin(COMPILER.resolve()), pin(reference_path),
                  pin(output / "sources.tar.gz")] +
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

    save()
    try:
        profile = LOCAL if len(cpus) == 1 else LOCAL_PARALLEL
        with reservation(output, settings(profile, len(cpus)), 600) as safety:
            report.update(status="BUILDING_FRESH_CORE", safety=safety); save()
            build = output / "build"
            checked(configure_command(build), "configure")
            # EXCLUDE_FROM_ALL in the experiment project requires an explicit core build.
            checked(["cmake", "--build", str(build), "--target", "regraph_convergence_demo",
                     "regraph_credit_control_test", "-j1"], "build_harness")
            checked(["cmake", "--build", str(build / "simulator"), "-j1"], "build_core")
            checked(["ctest", "--test-dir", str(build / "simulator"), "--output-on-failure",
                     "--timeout", "600", "-j1"], "core_ctest", 2400)
            checked([str(build / "regraph_credit_control_test")], "control_test", 30)
            report["pins"] += [pin(build / name) for name in ("CMakeCache.txt", "compile_commands.json",
                "regraph_convergence_demo", "simulator/cpp/libspine_cycle_core.a",
                "simulator/cpp/liboriginal_regraph_cycle.a")]
            verify()
            report["status"] = "RUNNING_COMPLETE_CONVERGENCE_MATRIX"; save()
            with ProcessPoolExecutor(max_workers=len(cpus),
                    mp_context=multiprocessing.get_context("spawn")) as pool:
                futures = []
                for index, case in enumerate(MATRIX):
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
            report["r_rows"].sort(key=lambda row: MATRIX.index((row["latency"], row["reverse"], row["arm"])))
            if report["failures"]:
                raise ValueError("matrix contains retained failures")
            report["analysis"] = summarize(report["r_rows"], reference["r_rows"])
            report["progress"] = [pin(path) for path in sorted((output / "progress").rglob("*.csv"))]
            verify()
            report.update(status="COMPACT_CONVERGENCE_COMPLETE_NOT_HARDWARE_ADMISSION", pins_unchanged=True)
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
