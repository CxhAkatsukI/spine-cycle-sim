"""Fresh serial build and guarded full-convergence R credit sensitivity study."""

import argparse
import json
import os
from pathlib import Path
import shutil
import subprocess
import tarfile

from spine_cycle_sim.experiments.campaign_runtime import atomic_write_json, sha256_file
from ...upstream_controls.execution import run_bounded
from ..r_execution import run_case
from .admission import COMPETITORS, competitors, wait
from .analysis import MATRIX, identity, summarize
from .freeze import ROOT, pin

REGRESSION_TARGETS = ["original_regraph_sssp_" + name + "_tests"
                      for name in ("udf", "frontend", "apply", "round")] + [
    "routed_source_service_tests", "regraph_compute_port_tests", "routed_regraph_system_tests"]


def run(output, before, maximum_wait=43200, reservations=None):
    reservations = COMPETITORS if reservations is None else reservations
    frozen = json.loads((before / "freeze.json").read_text())
    if frozen["status"] != "PRE_EXTRACTION_FROZEN":
        raise ValueError("pre-extraction freeze required")
    if any(sha256_file(Path(p["path"])) != p["sha256"] for p in frozen["artifacts"] + frozen["external"]):
        raise ValueError("pre-extraction evidence changed")
    reference = json.loads((before / "reference.json").read_text())
    output.mkdir(parents=True, exist_ok=False)
    original_input = Path(next(p["path"] for p in frozen["external"]
                               if p["path"].endswith("/sssp_initial.u32le"))).parent
    shutil.copytree(original_input, output / "inputs/warm_update")
    sources = sorted(p for owner in ("cpp", "spine_cycle_sim/experiments/evaluation_impact",
                                    "spine_cycle_sim/experiments/upstream_controls")
                     for p in (ROOT / owner).rglob("*")
                     if p.is_file() and p.suffix in (".cpp", ".hpp", ".py", ".txt"))
    sources += [ROOT / "CMakeLists.txt", ROOT / "spine_cycle_sim/experiments/campaign_runtime.py"]
    with tarfile.open(output / "sources.tar.gz", "w:gz") as archive:
        for source in sources:
            archive.add(source, arcname=str(source.relative_to(ROOT)))
    report = {"status": "RUNNING_BUILD", "steps": [], "r_rows": [], "failures": [],
        "matrix": MATRIX, "regression_targets": REGRESSION_TARGETS,
        "pins": [pin(p) for p in sources] + [pin(before / "freeze.json"),
            pin(output / "sources.tar.gz")] + [pin(p) for p in sorted((output / "inputs/warm_update").iterdir())],
        "cpu": max(os.sched_getaffinity(0)), "maximum_cycles": 1_500_000_000,
        "timeout_seconds": 1800, "maximum_wait_seconds": maximum_wait, "admission_wait_seconds": 0,
        "git_head": subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT, text=True).strip(),
        "safety": {"build_limit_gib": 2, "build_reserve_gib": 8, "case_limit_gib": 4,
                   "case_reserve_gib": 24, "serial": True,
                   "competing_units_gib": reservations},
        "boundary": "same resident warm weighted SSSP compute to convergence; no G/host/DMA",
        "production_baseline_admitted": False}

    def save():
        atomic_write_json(output / "results.json", report)

    def execute(command, label, timeout=600):
        print("RUN r_credits " + label, flush=True)
        step = run_bounded(command, ROOT, output / "raw" / label,
                           timeout=timeout, memory_gib=2, reserve_gib=8)
        report["steps"].append(step)
        save()
        if step["exit_code"] or step["timed_out"]:
            raise ValueError("bounded build/check failed: " + label)
        return step

    save()
    try:
        execute(["g++", "--version"], "compiler")
        build = output / "build"
        execute(["cmake", "-S", str(ROOT / "cpp/tests/evaluation_impact"), "-B", str(build),
                 "-DCMAKE_BUILD_TYPE=Release", "-DCMAKE_EXPORT_COMPILE_COMMANDS=ON", "-DBUILD_TESTING=ON"], "configure")
        execute(["cmake", "--build", str(build), "--target", "regraph_convergence_demo",
                 "regraph_credit_control_test", *REGRESSION_TARGETS, "-j1"], "build", 1200)
        execute([str(build / "regraph_credit_control_test")], "control_test")
        execute(["ctest", "--test-dir", str(build / "simulator"), "--output-on-failure",
                 "--timeout", "120", "-j1", "-R", "^(" + "|".join(REGRESSION_TARGETS) + ")$"],
                "regression", 1200)
        report["pins"] += [pin(p) for p in (build / "regraph_convergence_demo", build / "regraph_credit_control_test",
            build / "CMakeCache.txt", build / "compile_commands.json", build / "simulator/cpp/libspine_cycle_core.a",
            build / "simulator/cpp/liboriginal_regraph_cycle.a")]
        report["pins"] += [pin(build / "simulator/cpp" / target) for target in REGRESSION_TARGETS]
        for case in MATRIX:
            remaining = max(0, maximum_wait - report["admission_wait_seconds"])
            report["admission_wait_seconds"] += wait(report, save, remaining, reservations)
            if any(sha256_file(Path(p["path"])) != p["sha256"] for p in report["pins"]):
                raise ValueError("pinned source/input/build identity changed before timing case")
            report["status"] = "RUNNING_SENSITIVITY_MATRIX"
            save()
            result = run_case(ROOT, output, build / "regraph_convergence_demo", report["cpu"],
                              report["maximum_cycles"], report["timeout_seconds"], case)
            report["steps"].append(result["step"])
            if "row" in result:
                report["r_rows"].append(result["row"])
            else:
                report["failures"].append(result)
            save()
        if report["failures"]:
            raise ValueError("sensitivity matrix contains retained failures")
        report["r_rows"].sort(key=lambda row: MATRIX.index(identity(row)))
        report["analysis"] = summarize(report["r_rows"], reference["r_rows"])
        if any(sha256_file(Path(p["path"])) != p["sha256"] for p in report["pins"]):
            raise ValueError("pinned source/input/build identity changed")
        report.update(status=report["analysis"]["status"], pins_unchanged=True)
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
    parser.add_argument("--maximum-wait", type=int, default=43200)
    for name, default in zip(("route", "cache", "search"), COMPETITORS):
        parser.add_argument("--" + name + "-unit", default=default)
    args = parser.parse_args()
    if args.maximum_wait < 0:
        parser.error("wait bound must be nonnegative")
    reservations = competitors(args.route_unit, args.cache_unit, args.search_unit)
    print(json.dumps({"status": run(args.output.resolve(), args.before.resolve(),
                                   args.maximum_wait, reservations)["status"]}))
