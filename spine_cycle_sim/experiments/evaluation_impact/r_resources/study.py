"""Build fresh libraries and audit constructed ports without executing cycles."""

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


def run(output):
    output.mkdir(parents=True, exist_ok=False)
    sources = sorted(p for owner in ("cpp", "spine_cycle_sim/experiments/evaluation_impact/r_resources")
                     for p in (ROOT / owner).rglob("*") if p.suffix in (".cpp", ".hpp", ".py", ".txt"))
    sources.append(ROOT / "CMakeLists.txt")
    report = {"status": "RUNNING", "steps": [], "pins": [pin(p) for p in sources],
              "git_head": subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT, text=True).strip(),
              "git_diff_sha256": hashlib.sha256(subprocess.check_output(["git", "diff"], cwd=ROOT)).hexdigest(),
              "cpu_affinity": [max(os.sched_getaffinity(0))],
              "safety": {"process_limit_gib": 2, "reserve_gib": 8, "serial_build": True},
              "boundary": "constructor-only resource audit; zero device cycles; no performance result"}

    def save():
        atomic_write_json(output / "results.json", report)

    def execute(command, label, timeout=600):
        print("RUN r_resources " + label, flush=True)
        step = run_bounded(command, ROOT, output / "raw" / label,
                           timeout=timeout, memory_gib=2, reserve_gib=8)
        report["steps"].append(step)
        save()
        if step["exit_code"] or step["timed_out"]:
            raise ValueError("resource audit step failed: " + label)
        return step

    save()
    try:
        with tarfile.open(output / "sources.tar.gz", "w:gz") as archive:
            for source in sources:
                archive.add(source, arcname=str(source.relative_to(ROOT)))
        report["pins"].append(pin(output / "sources.tar.gz"))
        execute(["g++", "--version"], "compiler")
        execute(["cmake", "--version"], "cmake_version")
        build = output / "build"
        execute(["cmake", "-S", str(ROOT / "cpp/tests/evaluation_impact"), "-B", str(build),
                 "-DCMAKE_BUILD_TYPE=Release", "-DCMAKE_EXPORT_COMPILE_COMMANDS=ON", "-DBUILD_TESTING=ON"], "configure")
        execute(["cmake", "--build", str(build), "--target", "regraph_resource_audit", "-j1"], "build", 1200)
        report["pins"] += [pin(p) for p in (build / "regraph_resource_audit", build / "CMakeCache.txt",
            build / "compile_commands.json", build / "simulator/cpp/libspine_cycle_core.a",
            build / "simulator/cpp/liboriginal_regraph_cycle.a")]
        step = execute(["taskset", "-c", str(report["cpu_affinity"][0]), str(build / "regraph_resource_audit")], "audit")
        report["analysis"] = analyze(Path(step["stdout"]).read_text())
        for identity in report["pins"]:
            if sha256_file(Path(identity["path"])) != identity["sha256"]:
                raise ValueError("resource audit pinned identity changed")
        report["pins_unchanged"] = True
        report["status"] = report["analysis"]["status"]
    except BaseException as error:
        report.update(status="FAILED_RETAINED", error=repr(error))
        save()
        raise
    save()
    print(json.dumps({"status": report["status"], "a4_masters": 13, "k4_masters": 9}), flush=True)
    return report


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    run(parser.parse_args().output.resolve())
