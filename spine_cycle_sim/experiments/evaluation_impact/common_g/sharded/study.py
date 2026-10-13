"""Run a complete, serial, memory-bounded and hash-pinned G batch diagnostic."""

import argparse
import json
import os
from pathlib import Path

from spine_cycle_sim.experiments.campaign_runtime import atomic_write_json, sha256_file
from spine_cycle_sim.experiments.upstream_controls.execution import run_bounded
from ..study import ROOT
from .analysis import analyze
from .preparation import STATUS, input_contract


def input_arguments(item, contract, target):
    if target == "sharded_g_execution":
        return []
    if target not in ("real_sharded_g_execution", "metadata_layout_g_execution"):
        raise ValueError("undeclared sharded-G execution target")
    return [contract["cases"][item["case"]][key] for key in ("graph", "updates")]


def run(output, core_build, *, contract=None, analyze_rows=analyze,
        target="sharded_g_execution", tag="SHARDED_G_RESULT", status=STATUS):
    output.mkdir(parents=True, exist_ok=False)
    contract = input_contract() if contract is None else contract
    report = {"status": "RUNNING", "rows": [], "steps": [], "errors": [], "pins": [],
              "contract": contract, "matrix": contract["matrix"]}

    def pin(paths):
        report["pins"].extend({"path": str(p), "sha256": sha256_file(p)} for p in paths)

    def save():
        atomic_write_json(output / "results.json", report)

    def execute(command, label):
        print("RUN sharded-G " + label, flush=True)
        step = run_bounded(command, ROOT, output / "raw" / label,
                           timeout=600, memory_gib=2, reserve_gib=8)
        report["steps"].append(step)
        save()
        if step["exit_code"] or step["timed_out"]:
            raise ValueError("bounded sharded-G execution failed: " + label)
        return step

    owners = ("cpp/src", "cpp/include", "cpp/tests/original_grasu", "cpp/tests/evaluation_impact/common_g",
              "spine_cycle_sim/experiments/evaluation_impact/common_g")
    pin(sorted(p for owner in owners for p in (ROOT / owner).rglob("*")
               if p.suffix in (".cpp", ".hpp", ".py", ".txt")))
    config_root = core_build if (core_build / "CMakeCache.txt").is_file() else core_build.parent
    pin([core_build / name for name in ("liboriginal_grasu_cycle.a", "libspine_cycle_core.a")])
    pin([config_root / name for name in ("CMakeCache.txt", "compile_commands.json")])
    report["input_pins"] = contract.get("input_pins", [])
    if any(sha256_file(Path(item["path"])) != item["sha256"] for item in report["input_pins"]):
        raise ValueError("declared input hash differs before execution")
    pin([Path(item["path"]) for item in report["input_pins"]])
    atomic_write_json(output / "input_contract.json", report["contract"])
    pin([output / "input_contract.json"])
    save()
    try:
        execute(["g++", "--version"], "compiler")
        execute(["cmake", "--version"], "cmake")
        build = output / "build"
        execute(["cmake", "-S", str(ROOT / "cpp/tests/evaluation_impact/common_g"), "-B", str(build),
                 "-DCMAKE_BUILD_TYPE=Release", "-DCMAKE_EXPORT_COMPILE_COMMANDS=ON",
                 "-DCORE_BUILD=" + str(core_build)], "configure")
        execute(["cmake", "--build", str(build), "--target", target, "-j1"], "build")
        binary = build / target
        pin([binary, build / "CMakeCache.txt", build / "compile_commands.json"])
        affinity = str(sorted(os.sched_getaffinity(0))[-1])
        report["affinity"] = affinity
        for item in report["matrix"]:
            label = f"lat{item['latency']}_{item['case']}_{item['arm']}"
            state = output / (label + ".u32le")
            try:
                extra = input_arguments(item, contract, target)
                step = execute(["taskset", "-c", affinity, str(binary), item["case"], str(item["latency"]),
                                item["arm"], str(state), *extra], label)
                text = Path(step["stdout"]).read_text().strip()
                observed_tag, _, body = text.partition(" ")
                if observed_tag != tag:
                    raise ValueError("missing unique sharded-G result")
                report["rows"].append({**item, "observation": json.loads(body),
                                       "state_sha256": sha256_file(state), "state_path": str(state)})
            except (ValueError, RuntimeError) as error:
                report["errors"].append({**item, "error": str(error)})
            save()
        report.update(analyze_rows(report["rows"]))
        if any(sha256_file(Path(p["path"])) != p["sha256"] for p in report["pins"]):
            raise ValueError("frozen source, library, input or binary changed")
        report["status"] = status
    except BaseException as error:
        report["status"] = "FAILED_RETAINED"
        report["error"] = repr(error)
        save()
        raise
    save()
    print(json.dumps({key: report[key] for key in ("status", "prediction_rows", "comparisons",
        "four_bank_ten_percent_target_met", "runtime_ten_percent_diagnostic_met")}), flush=True)
    return report


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--core-build", required=True, type=Path)
    args = parser.parse_args()
    run(args.output.resolve(), args.core_build.resolve())
