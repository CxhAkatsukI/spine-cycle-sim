"""Bounded three-arm G predictions with independent HLS-helper source checks."""

import argparse
import json
import os
from pathlib import Path

from spine_cycle_sim.experiments.campaign_runtime import atomic_write_json, sha256_file
from spine_cycle_sim.experiments.upstream_controls.execution import run_bounded
from ..study import ROOT
from .analysis import summarize
from .preparation import CASES, prepare
from .validation import validate_matrix


def run(output, core_build, previous, hls_include):
    output.mkdir(parents=True, exist_ok=False)
    report = {"status": "RUNNING", "rows": [], "steps": [], "errors": [], "pins": [],
        "timing_kind": "declared_prediction", "hardware_timing_admitted": False,
        "publication_match_admitted": False, "production_baseline_admitted": False,
        "boundary": "resident prepared single destination window, update start through memory drain",
        "clock_mhz": 200, "banks": 4, "bank_credits": 32, "search_lanes_per_cu": 16,
        "matrix": [(latency, name, count, arm) for latency in (64, 128)
                   for name, count, _ in CASES for arm in ("original", "current", "parallel")]}
    sources = [p for owner in ("cpp/src", "cpp/include", "cpp/tests/original_grasu",
               "cpp/tests/evaluation_impact/common_g", "spine_cycle_sim/experiments/evaluation_impact/common_g")
               for p in (ROOT / owner).rglob("*") if p.suffix in (".cpp", ".hpp", ".py", ".txt")]
    sources += [core_build / name for name in ("liboriginal_grasu_cycle.a", "libspine_cycle_core.a")]
    sources.append(previous)
    report["pins"] = [{"path": str(p), "sha256": sha256_file(p)} for p in sources]

    def save():
        atomic_write_json(output / "results.json", report)

    def execute(command, label):
        print("RUN g_parallel " + label, flush=True)
        step = run_bounded(command, ROOT, output / "raw" / label, timeout=600, memory_gib=4, reserve_gib=24)
        report["steps"].append(step); save()
        if step["exit_code"] or step["timed_out"]:
            raise ValueError("G parallel step failed: " + label)
        return step

    save()
    try:
        build = output / "build"
        execute(["g++", "--version"], "compiler_version")
        execute(["cmake", "--version"], "cmake_version")
        execute(["cmake", "-S", str(ROOT / "cpp/tests/evaluation_impact/common_g"), "-B", str(build),
                 "-DCMAKE_BUILD_TYPE=Release", "-DCMAKE_EXPORT_COMPILE_COMMANDS=ON", "-DCORE_BUILD=" + str(core_build)], "configure")
        execute(["cmake", "--build", str(build), "-j1"], "build")
        binary = build / "common_g_execution"
        control = build / "hls_source_control"
        execute(["g++", "-O2", "-std=c++20", "-D_GTHREAD_USE_COND_INIT_FUNC", "-Wno-unknown-pragmas",
                 "-I" + str(ROOT / "cpp/include"), "-I" + str(hls_include),
                 str(ROOT / "cpp/tests/evaluation_impact/common_g/hls/source_control.cpp"),
                 str(core_build / "liboriginal_grasu_cycle.a"), str(core_build / "libspine_cycle_core.a"),
                 "-lgmp", "-o", str(control)], "source_build")
        prepare(output / "inputs")
        report["pins"].extend({"path": str(p), "sha256": sha256_file(p)} for p in
            [binary, control, build / "CMakeCache.txt", build / "compile_commands.json"] + list((output / "inputs").glob("*/*")))
        affinity = str(sorted(os.sched_getaffinity(0))[-1]); report["affinity"] = affinity
        for name, _, _ in CASES:
            execute(["taskset", "-c", affinity, str(control), str(output / "inputs" / name)], "source_" + name)
        for latency, name, count, arm in report["matrix"]:
            label = f"lat{latency}_{name}_{arm}"; state = output / (label + ".u32le")
            try:
                step = execute(["taskset", "-c", affinity, str(binary), str(output / "inputs" / name),
                                str(state), str(latency), arm], label)
                tag, _, body = Path(step["stdout"]).read_text().strip().partition(" ")
                if tag != "COMMON_G_RESULT":
                    raise ValueError("missing G observation")
                observation = json.loads(body)
                if observation["arm"] != arm or observation["state_pass"] is not True:
                    raise ValueError("G identity/correctness failure")
                report["rows"].append({"latency": latency, "case": name, "updates": count,
                    "arm": arm, "observation": observation, "state_sha256": sha256_file(state)})
            except ValueError as error:
                report["errors"].append({"case": label, "error": str(error)})
            save()
        if report["errors"]:
            raise ValueError("predeclared matrix has failed cases; all attempts retained")
        validate_matrix(report)
        report.update(summarize(report["rows"], json.loads(previous.read_text())))
        if any(sha256_file(Path(pin["path"])) != pin["sha256"] for pin in report["pins"]):
            raise ValueError("frozen identity changed during G experiment")
        report["status"] = "PREDICTION_AND_SOURCE_HELPERS_PASS_NOT_HARDWARE_ADMISSION"
    except BaseException as error:
        report["status"] = "FAILED_RETAINED"; report["error"] = repr(error); save(); raise
    save()
    print(json.dumps({key: report[key] for key in ("status", "comparisons", "default_regression_rows")}), flush=True)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--core-build", type=Path, required=True)
    parser.add_argument("--previous", type=Path, required=True)
    parser.add_argument("--hls-include", type=Path, default=Path("/data/yxx/tools/xilinx/Vitis_HLS/2024.1/include"))
    args = parser.parse_args()
    run(args.output.resolve(), args.core_build.resolve(), args.previous.resolve(), args.hls_include.resolve())
