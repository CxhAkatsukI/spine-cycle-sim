"""One bounded, hash-pinned execution owner for complete common-G matrices."""

from dataclasses import dataclass
import json
import os
from pathlib import Path
from typing import Callable

from spine_cycle_sim.experiments.campaign_runtime import atomic_write_json, sha256_file
from spine_cycle_sim.experiments.upstream_controls.execution import run_bounded
from .study import ROOT


@dataclass(frozen=True)
class Study:
    name: str
    matrix: Callable
    prepare: Callable
    analyze: Callable
    metadata: dict
    status: str
    summary_keys: tuple


def run(output, core_build, previous, study):
    output.mkdir(parents=True, exist_ok=False)
    report = {**study.metadata, "status": "RUNNING", "rows": [], "steps": [],
              "errors": [], "pins": [], "matrix": study.matrix()}
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
        print("RUN " + study.name + " " + label, flush=True)
        step = run_bounded(command, ROOT, output / "raw" / label,
                           timeout=600, memory_gib=1, reserve_gib=8)
        report["steps"].append(step)
        save()
        if step["exit_code"] or step["timed_out"]:
            raise ValueError(study.name + " step failed: " + label)
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
        study.prepare(output / "inputs")
        report["pins"].extend({"path": str(p), "sha256": sha256_file(p)} for p in
            [binary, build / "CMakeCache.txt", build / "compile_commands.json"] +
            sorted((output / "inputs").glob("*/*")))
        affinity = str(sorted(os.sched_getaffinity(0))[-1])
        report["affinity"] = affinity
        for latency, name, count, arm in report["matrix"]:
            label = f"lat{latency}_{name}_{arm}"
            state = output / (label + ".u32le")
            try:
                step = execute(["taskset", "-c", affinity, str(binary), str(output / "inputs" / name),
                                str(state), str(latency), arm], label)
                tag, _, body = Path(step["stdout"]).read_text().strip().partition(" ")
                if tag != "COMMON_G_RESULT":
                    raise ValueError("missing unique common-G observation")
                report["rows"].append({"latency": latency, "case": name, "updates": count,
                    "arm": arm, "observation": json.loads(body), "state_sha256": sha256_file(state)})
            except ValueError as error:
                report["errors"].append({"case": label, "error": str(error)})
            save()
        report.update(study.analyze(report, json.loads(previous.read_text())))
        if any(sha256_file(Path(p["path"])) != p["sha256"] for p in report["pins"]):
            raise ValueError("pinned source/input/binary changed during execution")
        report["status"] = study.status
    except BaseException as error:
        report["status"] = "FAILED_RETAINED"
        report["error"] = repr(error)
        save()
        raise
    save()
    print(json.dumps({key: report[key] for key in ("status",) + study.summary_keys}))
    return report
