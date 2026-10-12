"""Run bounded original-G replay and compute-only R convergence diagnostics."""

import argparse
import json
import os
from pathlib import Path
import shutil
import subprocess

from spine_cycle_sim.experiments.campaign_runtime import atomic_write_json, sha256_file
from ..upstream_controls.execution import run_bounded
from .analysis import MATRIX, summarize
from .grasu import replay
from .r_execution import run_matrix

ROOT = Path(__file__).resolve().parents[3]


def pin(path):
    return {"path": str(path), "sha256": sha256_file(path), "bytes": path.stat().st_size}


def run(output, basis, grasu_report, jobs=1, maximum_cycles=1_500_000_000, timeout=1800):
    output.mkdir(parents=True, exist_ok=False)
    sources = [p for owner in ("cpp/src", "cpp/include", "cpp/tests", "spine_cycle_sim/experiments/evaluation_impact")
               for p in (ROOT / owner).rglob("*") if p.is_file() and p.suffix in (".cpp", ".hpp", ".py", ".txt")]
    sources += [ROOT / "CMakeLists.txt", ROOT / "cpp/CMakeLists.txt"]
    plugin = ROOT / "build/sst/libspine_cycle.so"
    pins = [pin(p) for p in sorted(set(sources))] + [pin(plugin), pin(grasu_report), pin(basis / "results.json")]
    shutil.copytree(basis / "inputs/warm_update", output / "inputs/warm_update")
    pins += [pin(p) for p in sorted((output / "inputs/warm_update").iterdir()) if p.is_file()]
    cpus = sorted(os.sched_getaffinity(0))[-jobs:]
    affinity = ",".join(map(str, cpus))
    report = {"status": "RUNNING", "pins": pins, "steps": [], "r_rows": [], "affinity": affinity,
        "git_head": subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT, text=True).strip(),
        "git_diff_sha256": __import__("hashlib").sha256(subprocess.check_output(["git", "diff"], cwd=ROOT)).hexdigest(),
        "compiler": subprocess.check_output(["g++", "--version"], text=True),
        "matrix": MATRIX, "jobs": jobs, "maximum_cycles": maximum_cycles, "case_timeout_seconds": timeout,
        "boundary": "resident warm post-update SSSP compute to convergence, excludes G and host",
        "g_performance_gate": "OPEN", "publication_match_gate": "OPEN", "complete_spine_gr_comparison": False}
    path = output / "results.json"

    def save():
        atomic_write_json(path, report)

    def execute(command, label, timeout=600):
        print("RUN " + label, flush=True)
        result = run_bounded(command, ROOT, output / "raw" / label,
                             timeout=timeout, memory_gib=4, reserve_gib=24)
        report["steps"].append(result); save()
        if result["exit_code"] or result["timed_out"]:
            raise ValueError("bounded diagnostic failed: " + label)
        return result

    save()
    try:
        build = output / "build"
        execute(["cmake", "-S", str(ROOT / "cpp/tests/evaluation_impact"), "-B", str(build),
                 "-DCMAKE_BUILD_TYPE=Release", "-DCMAKE_EXPORT_COMPILE_COMMANDS=ON", "-DBUILD_TESTING=ON"], "configure")
        execute(["cmake", "--build", str(build), "--target", "regraph_convergence_demo",
                 "original_grasu_execution", "original_grasu_tests", "-j2"], "build", timeout=1200)
        binaries = [build / "regraph_convergence_demo", build / "simulator/cpp/original_grasu_execution",
                    build / "simulator/cpp/original_grasu_tests"]
        pins += [pin(p) for p in (*binaries, build / "CMakeCache.txt", build / "compile_commands.json")]
        execute([str(binaries[2])], "g_component_tests")
        report["g"] = replay(ROOT, json.loads(grasu_report.read_text()), binaries[1], output / "g", execute)
        save()
        def record_case(case):
            report["steps"].append(case["step"])
            if "row" in case:
                report["r_rows"].append(case["row"])
            else:
                report.setdefault("r_failures", []).append(case)
            save()
        run_matrix(ROOT, output, binaries[0], cpus, maximum_cycles, timeout, record_case)
        report["r_rows"].sort(key=lambda r: MATRIX.index((r["latency"], r["reverse"], r["arm"])))
        if report.get("r_failures"):
            raise ValueError("R matrix contains retained failures")
        report["r"] = summarize(report["r_rows"])
        if any(sha256_file(Path(p["path"])) != p["sha256"] for p in pins):
            raise ValueError("frozen diagnostic identity changed during execution")
        report["status"] = "DIAGNOSTIC_COMPLETE_BASELINE_PERFORMANCE_GATES_OPEN"
        report["pins_unchanged"] = True
    except BaseException as error:
        report["status"] = "FAILED_RETAINED"
        report["error"] = repr(error)
        save()
        raise
    save()
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("output", "basis", "grasu-report"):
        parser.add_argument("--" + name, type=Path, required=True)
    parser.add_argument("--jobs", type=int, choices=range(1, 5), default=1)
    parser.add_argument("--maximum-cycles", type=int, default=1_500_000_000)
    parser.add_argument("--case-timeout", type=int, default=1800)
    args = parser.parse_args()
    if args.maximum_cycles <= 0 or args.case_timeout <= 0:
        parser.error("cycle and wall-time bounds must be positive")
    result = run(args.output.resolve(), args.basis.resolve(), args.grasu_report.resolve(),
                 args.jobs, args.maximum_cycles, args.case_timeout)
    print(json.dumps({"status": result["status"], "r": result["r"]}), flush=True)


if __name__ == "__main__":
    main()
