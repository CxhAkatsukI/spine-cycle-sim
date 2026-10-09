"""Bounded original Big routing/Gather matrix and unchanged-A4 regression."""

import json
from pathlib import Path
import shutil
import subprocess

from spine_cycle_sim.experiments.campaign_runtime import atomic_write_json, sha256_file
from spine_cycle_sim.experiments.original_regraph_validation.analysis import same_typed
from spine_cycle_sim.experiments.original_regraph_validation.instrumentation import sanitize_cases
from spine_cycle_sim.experiments.upstream_controls.execution import run_bounded
from .analysis import STATUS, analyze_tests, analyze_comparison
from .sources import capture_source
from .regression import verify_legacy


def source_identities(root: Path) -> list[dict]:
    paths = [root / name for name in ("cpp/CMakeLists.txt", "CMakeLists.txt",
        "scripts/run_original_regraph_big_validation.py", "tests/test_original_regraph_big_validation.py",
        "cpp/tests/publication_sources/regraph_big_gather_probe.cpp")]
    for directory, pattern in (("cpp/include/spine_sim", "*.hpp"), ("cpp/src", "*.cpp"),
        ("cpp/tests/original_regraph", "*.hpp"), ("cpp/tests/original_regraph", "*.cpp"),
        ("spine_cycle_sim/experiments/original_regraph_validation", "*.py"),
        ("spine_cycle_sim/experiments/upstream_controls", "*.py")):
        paths.extend((root / directory).rglob(pattern))
    return [{"path": str(path.relative_to(root)), "sha256": sha256_file(path)} for path in sorted(set(paths))]


def run_study(root: Path, source: Path, hls: Path, baseline: Path, output: Path) -> dict:
    contract_path = root / "configs/experiments/original_regraph_big_gather_validation_v1.json"
    contract = json.loads(contract_path.read_text())
    output.mkdir(parents=True, exist_ok=False)
    shutil.copyfile(contract_path, output / "contract.json")
    compiler = shutil.which("g++")
    if compiler is None or not (hls / "ap_int.h").is_file():
        raise ValueError("Big source control requires G++ and Vitis headers")
    report = {"schema_version": 1, "status": "NOT_COMPLETED", "evidence_class": contract["evidence_class"],
        "boundary": contract["boundary"], "contract_sha256": sha256_file(contract_path), "steps": [], "binaries": [],
        "source_identities": source_identities(root), "source_revision": subprocess.check_output(
            ["git", "rev-parse", "HEAD"], cwd=root, text=True).strip(),
        "worktree_status": subprocess.check_output(["git", "status", "--porcelain"], cwd=root, text=True).splitlines(),
        "compiler_version": subprocess.check_output([compiler, "--version"], text=True),
        "not_claimed": contract["not_claimed"], "FPGA_cycles": None, "publication_error_pct": None}

    def execute(name, command, timeout, expected_failure=False):
        print(f"Starting {name} (Big component cycles predicted, not FPGA)", flush=True)
        row = {"id": name, **run_bounded(command, root, output / name, timeout=timeout,
            memory_gib=contract["memory_limit_gib"], reserve_gib=contract["reserve_gib"])}
        report["steps"].append(row)
        atomic_write_json(output / "report.json", report)
        if row["timed_out"] or not expected_failure and row["exit_code"] != 0:
            raise ValueError(f"{name} failed; attempt preserved")
        return row

    try:
        report["source_control"] = capture_source(root, output, source, hls, contract, compiler, execute)
        build = output / "build"
        execute("configure", ["cmake", "-S", str(root), "-B", str(build), "-DCMAKE_BUILD_TYPE=Release",
            "-DCMAKE_EXPORT_COMPILE_COMMANDS=ON", f"-DCMAKE_CXX_COMPILER={compiler}"], contract["build_timeout_seconds"])
        execute("build", ["cmake", "--build", str(build), f"-j{contract['build_jobs']}"], contract["build_timeout_seconds"])
        expected = {}
        for name in ("big_tests", "big_comparison"):
            binary = build / "cpp" / ("original_regraph_" + name)
            report["binaries"].append({"path": str(binary), "sha256": sha256_file(binary)})
            arguments = [] if name == "big_tests" else [report["source_control"]["capture"]["path"]]
            for repetition in ("first", "repeat"):
                step = execute(name + "_" + repetition, [str(binary), *arguments], contract["run_timeout_seconds"])
                text = Path(step["stdout"]).read_text()
                if Path(step["stderr"]).read_text(): raise ValueError("unexpected Big runtime diagnostics")
                (analyze_tests if name == "big_tests" else analyze_comparison)(text, contract)
                if repetition == "first": expected[name] = text
                elif text != expected[name]: raise ValueError("Big repeated values/cycles/counters changed")
            report[name] = (analyze_tests if name == "big_tests" else analyze_comparison)(expected[name], contract)
        execute("ctest", ["ctest", "--test-dir", str(build), "--output-on-failure"], contract["run_timeout_seconds"])
        report["legacy"] = verify_legacy(root, build, output, baseline, contract, execute)
        report["negative_controls"] = []
        original = Path(report["source_control"]["capture"]["path"])
        for kind in ("changed", "truncated", "excess"):
            damaged = output / (kind + ".u32le")
            payload = original.read_bytes()
            damaged.write_bytes((bytes([payload[0] ^ 1]) + payload[1:]) if kind == "changed"
                                else payload[:-4] if kind == "truncated" else payload + bytes(4))
            step = execute("negative_" + kind, [str(build / "cpp/original_regraph_big_comparison"), str(damaged)],
                           contract["run_timeout_seconds"], True)
            if step["exit_code"] == 0: raise ValueError("damaged Big capture accepted")
            report["negative_controls"].append({"id": kind, "rejected": True, "sha256": sha256_file(damaged)})
        report["binaries"] += sanitize_cases(root, output, compiler, execute, {
            "big_tests": ("big_tests.cpp", [], expected["big_tests"]),
            "big_comparison": ("big_comparison.cpp", [str(original)], expected["big_comparison"])},
            contract["build_timeout_seconds"], contract["run_timeout_seconds"])
        report["ubsan_identical_no_diagnostics"] = True
        for item in report["source_identities"]:
            if sha256_file(root / item["path"]) != item["sha256"]: raise ValueError("Big model/runner changed during study")
        if not same_typed(contract, json.loads(contract_path.read_text())): raise ValueError("Big contract changed")
        for item in report["source_control"]["dependencies"] + report["binaries"] + [report["source_control"]["capture"], report["source_control"]["binary"]]:
            if sha256_file(Path(item["path"])) != item["sha256"]: raise ValueError("Big tested source/binary/capture changed")
        report["status"] = STATUS
    except (ValueError, RuntimeError, OSError, subprocess.SubprocessError) as error:
        report["status"], report["error"] = "FAILED", str(error)
    atomic_write_json(output / "report.json", report)
    return report
