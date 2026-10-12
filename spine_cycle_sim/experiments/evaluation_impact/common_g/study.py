"""Compare unchanged current/original G predictions on matched resident inputs."""

import argparse
import json
import os
from pathlib import Path

from spine_cycle_sim.experiments.campaign_runtime import atomic_write_json, sha256_file
from ...upstream_controls.execution import run_bounded
from .preparation import COUNTS, prepare

ROOT = Path(__file__).resolve().parents[4]


def run(output, core_build):
    output.mkdir(parents=True, exist_ok=False)
    report = {"status": "RUNNING", "rows": [], "steps": [], "pins": [],
        "timing_kind": "declared_prediction", "hardware_timing_admitted": False,
        "publication_match_admitted": False, "production_baseline_admitted": False,
        "boundary": "resident prepared single destination window, update start through memory drain",
        "clock_mhz": 200, "banks": 4, "bank_credits": 32,
        "matrix": [(latency, count, arm) for latency in (64, 128) for count in COUNTS for arm in ("original", "current")]}
    paths = [p for owner in ("cpp/src", "cpp/include", "cpp/tests/original_grasu", "cpp/tests/evaluation_impact/common_g",
                            "spine_cycle_sim/experiments/evaluation_impact/common_g")
             for p in (ROOT / owner).rglob("*") if p.suffix in (".cpp", ".hpp", ".py", ".txt")]
    paths += [core_build / name for name in ("liboriginal_grasu_cycle.a", "libspine_cycle_core.a")]
    report["pins"] = [{"path": str(p), "sha256": sha256_file(p)} for p in paths]

    def save():
        atomic_write_json(output / "results.json", report)

    def execute(command, label):
        print("RUN common_g_" + label, flush=True)
        step = run_bounded(command, ROOT, output / "raw" / label, timeout=600, memory_gib=4, reserve_gib=24)
        report["steps"].append(step); save()
        if step["exit_code"] or step["timed_out"]:
            raise ValueError("matched G diagnostic failed: " + label)
        return step

    save()
    try:
        build = output / "build"
        execute(["cmake", "-S", str(ROOT / "cpp/tests/evaluation_impact/common_g"), "-B", str(build),
                 "-DCMAKE_BUILD_TYPE=Release", "-DCMAKE_EXPORT_COMPILE_COMMANDS=ON", "-DCORE_BUILD=" + str(core_build)], "configure")
        execute(["cmake", "--build", str(build), "-j1"], "build")
        binary = build / "common_g_execution"
        report["pins"].extend({"path": str(p), "sha256": sha256_file(p)} for p in
            (binary, build / "CMakeCache.txt", build / "compile_commands.json"))
        for count in COUNTS:
            directory = output / "inputs" / str(count)
            prepare(directory, count)
            report["pins"].extend({"path": str(p), "sha256": sha256_file(p)} for p in sorted(directory.iterdir()))
        affinity = str(sorted(os.sched_getaffinity(0))[-1])
        report["affinity"] = affinity
        for latency, count, arm in report["matrix"]:
            label = f"lat{latency}_n{count}_{arm}"
            state = output / (label + ".u32le")
            step = execute(["taskset", "-c", affinity, str(binary), str(output / "inputs" / str(count)),
                            str(state), str(latency), arm], label)
            text = Path(step["stdout"]).read_text().strip()
            tag, _, body = text.partition(" ")
            if tag != "COMMON_G_RESULT":
                raise ValueError("missing unique G result")
            row = json.loads(body)
            if row["arm"] != arm or row["state_pass"] is not True:
                raise ValueError("G execution identity or state mismatch")
            report["rows"].append({"latency": latency, "updates": count, "observation": row, "state_sha256": sha256_file(state)})
            save()
        comparisons = []
        for latency in (64, 128):
            for count in COUNTS:
                pair = [r for r in report["rows"] if r["latency"] == latency and r["updates"] == count]
                if len(pair) != 2 or pair[0]["state_sha256"] != pair[1]["state_sha256"]:
                    raise ValueError("G matched state differs between arms")
                values = {r["observation"]["arm"]: r["observation"] for r in pair}
                if any(values["original"][k] != values["current"][k] for k in ("cache_updates", "ddr_updates")):
                    raise ValueError("G logical route counts differ")
                comparisons.append({"latency": latency, "updates": count,
                    "current_over_original_cycles": values["current"]["cycles"] / values["original"]["cycles"],
                    "arms": values})
        report["comparisons"] = comparisons
        report["ten_percent_model_target_met"] = all(0.9 <= r["current_over_original_cycles"] <= 1.1 for r in comparisons)
        if any(sha256_file(Path(p["path"])) != p["sha256"] for p in report["pins"]):
            raise ValueError("matched G frozen identity changed")
        report["status"] = "MATCHED_G_DIAGNOSTIC_COMPLETE_NOT_TIMING_ADMISSION"
    except BaseException as error:
        report["status"] = "FAILED_RETAINED"; report["error"] = repr(error); save(); raise
    save()
    print(json.dumps({k: report[k] for k in ("status", "comparisons", "ten_percent_model_target_met")}), flush=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--core-build", type=Path, required=True)
    args = parser.parse_args()
    run(args.output.resolve(), args.core_build.resolve())


if __name__ == "__main__":
    main()
