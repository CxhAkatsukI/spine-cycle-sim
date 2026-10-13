"""Freeze, build and verify resident G->R without rebuilding its PMA input."""

import argparse
import hashlib
import json
import os
from pathlib import Path
import subprocess
import tarfile

from spine_cycle_sim.experiments.campaign_runtime import atomic_write_json, sha256_file
from spine_cycle_sim.experiments.upstream_controls.execution import run_bounded
from .analysis import analyze

ROOT = Path(__file__).resolve().parents[4]


def pin(path):
    return {"path": str(path), "sha256": sha256_file(path), "bytes": path.stat().st_size}


def run(output, previous_stdout, core_build=None):
    output.mkdir(parents=True, exist_ok=False)
    sources = sorted(p for owner in ("cpp", "spine_cycle_sim/experiments/evaluation_impact/composition")
                     for p in (ROOT / owner).rglob("*")
                     if p.is_file() and (p.suffix in (".cpp", ".hpp", ".py", ".txt") or p.name == "Makefile"))
    sources.append(ROOT / "CMakeLists.txt")
    report = {"status": "RUNNING", "steps": [], "pins": [pin(p) for p in sources + [previous_stdout]],
        "git_head": subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT, text=True).strip(),
        "git_diff_sha256": hashlib.sha256(subprocess.check_output(["git", "diff"], cwd=ROOT)).hexdigest(),
        "affinity": max(os.sched_getaffinity(0)), "clock_mhz": 150,
        "memory_model": {"channels": 32, "latency_cycles": 7, "issue_per_channel": 1,
                         "outstanding_per_channel": 16, "response_depth": 32},
        "g_implementation": "unchanged legacy direct sharded G, not finite cached candidate",
        "boundary": "G drained -> same physical rows/slots -> warm SSSP R convergence; state/seed and setup untimed",
        "baseline_admitted": False, "hardware_timing_admitted": False,
        "safety": {"process_limit_gib": 2, "reserve_gib": 8, "serial_build_and_tests": True}}

    def save():
        atomic_write_json(output / "results.json", report)

    def execute(command, label, timeout=600):
        print("RUN composition " + label, flush=True)
        step = run_bounded(["taskset", "-c", str(report["affinity"]), *command], ROOT,
                           output / "raw" / label, timeout=timeout, memory_gib=2, reserve_gib=8)
        report["steps"].append({"label": label, **step})
        save()
        if step["exit_code"] or step["timed_out"]:
            raise ValueError("composition check failed: " + label)
        return step

    save()
    try:
        with tarfile.open(output / "sources.tar.gz", "w:gz") as archive:
            for source in sources:
                archive.add(source, arcname=str(source.relative_to(ROOT)))
        report["pins"].append(pin(output / "sources.tar.gz"))
        execute(["g++", "--version"], "compiler")
        build = core_build or output / "build"
        execute(["cmake", "-S", str(ROOT), "-B", str(build), "-DCMAKE_BUILD_TYPE=Release",
                 "-DCMAKE_EXPORT_COMPILE_COMMANDS=ON"], "configure")
        execute(["cmake", "--build", str(build), "-j1"], "core-build", 1200)
        report["pins"] += [pin(p) for p in (build / "cpp/grasu_routed_handoff_tests",
            build / "cpp/routed_regraph_system_tests", build / "cpp/libspine_cycle_core.a",
            build / "compile_commands.json", build / "CMakeCache.txt")]
        handoff = execute([str(build / "cpp/grasu_routed_handoff_tests")], "handoff")
        report["analysis"] = analyze(Path(handoff["stdout"]).read_text())
        default = execute([str(build / "cpp/routed_regraph_system_tests")], "default-routed")
        report["default_routed_stdout_exact"] = Path(default["stdout"]).read_bytes() == previous_stdout.read_bytes()
        if not report["default_routed_stdout_exact"]:
            raise ValueError("default routed numerical observations changed")
        execute(["ctest", "--test-dir", str(build), "--output-on-failure", "-j1"], "ctest", 900)
        sst = output / "sst"
        execute(["make", "-C", "cpp/sst", "-j1", "BUILD_DIR=" + str(sst)], "sst-build", 900)
        report["pins"].append(pin(sst / "libspine_cycle.so"))
        execute(["/data/feiyang/sst/bin/sst-info", "--add-lib-path=" + str(sst), "spine_cycle"], "sst-info")
        execute(["python3", "scripts/run_sst_memory_smoke.py", "--no-build", "--lib-dir", str(sst),
                 "--out-dir", str(output / "sst-memory"), "--channels", "4", "--requests", "64"], "sst-memory")
        execute(["python3", "scripts/run_sst_grasu_regraph_native.py", "--no-build", "--lib-dir", str(sst),
                 "--out-dir", str(output / "sst-native"), "--max-cycles", "1000000"], "sst-native")
        if any(sha256_file(Path(p["path"])) != p["sha256"] for p in report["pins"]):
            raise ValueError("composition frozen identity changed")
        report.update(status=report["analysis"]["status"], pins_unchanged=True,
                      sst_scope="default-only compatibility, not resident/finite candidate timing")
    except BaseException as error:
        report.update(status="FAILED_RETAINED", error=repr(error))
        save()
        raise
    save()
    print(json.dumps({"status": report["status"], "handoff_rows": len(report["analysis"]["rows"]),
                      "default_routed_stdout_exact": report["default_routed_stdout_exact"]}), flush=True)
    return report


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--previous-stdout", type=Path, required=True)
    parser.add_argument("--core-build", type=Path)
    args = parser.parse_args()
    run(args.output.resolve(), args.previous_stdout.resolve(), args.core_build.resolve() if args.core_build else None)
