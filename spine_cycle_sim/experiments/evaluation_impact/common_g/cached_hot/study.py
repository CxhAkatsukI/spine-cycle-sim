"""Run complete cached-G controls with fixed low-memory serial admission."""

import argparse
import json
import os
from pathlib import Path

from spine_cycle_sim.experiments.campaign_runtime import atomic_write_json, sha256_file
from spine_cycle_sim.experiments.upstream_controls.execution import run_bounded
from ..study import ROOT
from .analysis import analyze
from .preparation import matrix, prepare


def run(output, core_build, previous):
    output.mkdir(parents=True, exist_ok=False)
    report = {"status": "RUNNING", "rows": [], "steps": [], "errors": [], "pins": [],
        "matrix": matrix(), "timing_kind": "declared_prediction",
        "hardware_timing_admitted": False, "publication_match_admitted": False,
        "production_baseline_admitted": False, "reference_cache_timing_admitted": False,
        "boundary": "prepared resident single window, cache preload through all cold/cache write acknowledgements and memory drain",
        "clock_mhz": 200, "banks": 4, "bank_credits": 32,
        "hot_cache_halves": 2, "hot_cache_bytes_per_half": 131072 * 64,
        "banks_per_half": 16, "bank_queue_depth": 2, "bank_pipeline_entries": 3,
        "bank_interval_cycles": 3, "bank_latency_cycles": 7,
        "assumptions": ["logical same-row forwarding in each finite bank pipeline",
            "isolated original/source16 RTL II=3 is not integrated-G clock calibration",
            "legacy original model blocks same-row input until retirement; reference correction remains open"],
        "safety": {"serial": True, "process_limit_gib": 1, "reserve_gib": 8,
            "basis": "previous identical-size 152-run study peak process RSS 342244 KiB; heavy HLS/routing thresholds unchanged"}}
    paths = [p for owner in ("cpp/src", "cpp/include", "cpp/tests/original_grasu",
        "cpp/tests/evaluation_impact/common_g", "spine_cycle_sim/experiments/evaluation_impact/common_g")
        for p in (ROOT / owner).rglob("*") if p.suffix in (".cpp", ".hpp", ".py", ".txt")]
    paths += [ROOT / "cpp/CMakeLists.txt", ROOT / "cpp/sst/Makefile", previous]
    paths += [core_build / name for name in ("liboriginal_grasu_cycle.a", "libspine_cycle_core.a")]
    configure_root = core_build if (core_build / "CMakeCache.txt").is_file() else core_build.parent
    paths += [configure_root / name for name in ("CMakeCache.txt", "compile_commands.json")]
    paths.append(ROOT / "cpp/tests/grasu_cached_processor_tests.cpp")
    report["pins"] = [{"path": str(p), "sha256": sha256_file(p)} for p in paths]

    def save():
        atomic_write_json(output / "results.json", report)

    def execute(command, label):
        print("RUN cached_g " + label, flush=True)
        step = run_bounded(command, ROOT, output / "raw" / label,
                           timeout=600, memory_gib=1, reserve_gib=8)
        report["steps"].append(step); save()
        if step["exit_code"] or step["timed_out"]:
            raise ValueError("cached-G step failed: " + label)
        return step

    save()
    try:
        execute(["g++", "--version"], "compiler_version")
        execute(["cmake", "--version"], "cmake_version")
        build = output / "build"
        execute(["cmake", "-S", str(ROOT / "cpp/tests/evaluation_impact/common_g"), "-B", str(build),
                 "-DCMAKE_BUILD_TYPE=Release", "-DCMAKE_EXPORT_COMPILE_COMMANDS=ON",
                 "-DCORE_BUILD=" + str(core_build)], "configure")
        execute(["cmake", "--build", str(build), "-j1"], "build")
        binary = build / "common_g_execution"
        prepare(output / "inputs")
        report["pins"].extend({"path": str(p), "sha256": sha256_file(p)} for p in
            [binary, build / "CMakeCache.txt", build / "compile_commands.json"] +
            sorted((output / "inputs").glob("*/*")))
        affinity = str(sorted(os.sched_getaffinity(0))[-1]); report["affinity"] = affinity
        for latency, name, count, arm in report["matrix"]:
            label = f"lat{latency}_{name}_{arm}"; state = output / (label + ".u32le")
            try:
                step = execute(["taskset", "-c", affinity, str(binary), str(output / "inputs" / name),
                                str(state), str(latency), arm], label)
                tag, _, body = Path(step["stdout"]).read_text().strip().partition(" ")
                if tag != "COMMON_G_RESULT":
                    raise ValueError("missing unique cached-G observation")
                report["rows"].append({"latency": latency, "case": name, "updates": count,
                    "arm": arm, "observation": json.loads(body), "state_sha256": sha256_file(state)})
            except ValueError as error:
                report["errors"].append({"case": label, "error": str(error)})
            save()
        report.update(analyze(report, json.loads(previous.read_text())))
        if any(sha256_file(Path(p["path"])) != p["sha256"] for p in report["pins"]):
            raise ValueError("pinned source/input/binary changed during execution")
        report["status"] = "CACHED_G_PREDICTION_VALIDATED_REFERENCE_TIMING_OPEN"
    except BaseException as error:
        report["status"] = "FAILED_RETAINED"; report["error"] = repr(error); save(); raise
    save()
    print(json.dumps({key: report[key] for key in ("status", "old_checkpoint_exact_rows",
        "legacy_reference_no_more_than_ten_percent_slower", "legacy_reference_within_ten_percent_both_directions")}))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    for key in ("output", "core-build", "previous"):
        parser.add_argument("--" + key, type=Path, required=True)
    args = parser.parse_args()
    run(args.output.resolve(), args.core_build.resolve(), args.previous.resolve())
