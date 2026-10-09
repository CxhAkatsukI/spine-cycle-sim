"""Isolated Release build and complete input-path/regression admission."""

from __future__ import annotations

import json
from pathlib import Path
import shutil
import subprocess

from spine_cycle_sim.experiments.campaign_runtime import atomic_write_json, sha256_file
from spine_cycle_sim.experiments.upstream_controls.execution import run_bounded
from .analysis import admit_captures, analyze, same_typed
from .frontend_analysis import admit_protocol, analyze_frontend
from .negative_controls import run_negative_controls
from .instrumentation import sanitize_cases
from .study import source_identities


def run_frontend_study(root: Path, contract_path: Path, captures: Path,
                       protocol: Path, output: Path) -> dict:
    canonical = root / "configs/experiments/original_regraph_frontend_validation_v1.json"
    contract = json.loads(contract_path.read_text())
    if not same_typed(contract, json.loads(canonical.read_text())):
        raise ValueError("unsupported frontend matrix; declare a new reviewed contract")
    gather_path = root / "configs/experiments/original_regraph_gather_validation_v1.json"
    gather_contract = json.loads(gather_path.read_text())
    captured = admit_captures(captures, root, contract)
    original = admit_protocol(protocol, root, contract)
    output.mkdir(parents=True, exist_ok=False)
    shutil.copyfile(contract_path, output / "contract.json")
    compiler = shutil.which("c++")
    if compiler is None:
        raise ValueError("C++ compiler required")
    identities = source_identities(root)
    report = {
        "schema_version": 1, "evidence_class": contract["evidence_class"],
        "boundary": contract["boundary"], "status": "NOT_COMPLETED",
        "contract_sha256": sha256_file(contract_path),
        "gather_contract_sha256": sha256_file(gather_path),
        "source_revision": subprocess.check_output(
            ["git", "rev-parse", "HEAD"], cwd=root, text=True).strip(),
        "worktree_status": subprocess.check_output(
            ["git", "status", "--porcelain"], cwd=root, text=True).splitlines(),
        "source_identities": identities, "source_captures": captured,
        "original_protocol": original, "steps": [], "not_claimed": contract["not_claimed"],
        "compiler_path": compiler,
        "compiler_version": subprocess.check_output([compiler, "--version"], text=True),
        "cmake_version": subprocess.check_output(["cmake", "--version"], text=True),
    }
    limits = {"memory_gib": contract["memory_limit_gib"], "reserve_gib": contract["reserve_gib"]}
    build = output / "build"

    def execute(name: str, command: list[str], timeout: int) -> dict:
        print(f"Starting {name} (original Little memory-to-merge only)", flush=True)
        step = {"id": name, **run_bounded(command, root, output / name, timeout=timeout, **limits)}
        report["steps"].append(step)
        atomic_write_json(output / "report.json", report)
        if step["exit_code"] != 0 or step["timed_out"]:
            raise ValueError(f"{name} failed; raw output retained")
        return step

    try:
        execute("configure", ["cmake", "-S", str(root), "-B", str(build),
                              "-DCMAKE_BUILD_TYPE=Release", "-DCMAKE_EXPORT_COMPILE_COMMANDS=ON",
                              f"-DCMAKE_CXX_COMPILER={compiler}"], contract["build_timeout_seconds"])
        execute("build", ["cmake", "--build", str(build), "--parallel",
                          str(contract["build_parallelism"])], contract["build_timeout_seconds"])
        binaries = [build / "cpp" / name for name in (
            "original_regraph_frontend_tests", "original_regraph_gather_tests",
            "original_regraph_source_comparison")]
        report["binaries"] = [{"path": str(path), "sha256": sha256_file(path)} for path in binaries]
        report["compile_commands_sha256"] = sha256_file(build / "compile_commands.json")
        report["cmake_cache_sha256"] = sha256_file(build / "CMakeCache.txt")
        first = execute("frontend", [str(binaries[0])], contract["run_timeout_seconds"])
        second = execute("frontend_repeat", [str(binaries[0])], contract["run_timeout_seconds"])
        invariant = execute("gather_invariants", [str(binaries[1])], contract["run_timeout_seconds"])
        command = [str(binaries[2]), *[row["path"] for row in captured]]
        comparison = execute("source_comparison", command, contract["run_timeout_seconds"])
        repeat = execute("source_comparison_repeat", command, contract["run_timeout_seconds"])
        execute("cpp_regression", ["ctest", "--test-dir", str(build), "--output-on-failure"],
                contract["run_timeout_seconds"])
        execute("python_regression", ["python3", "-m", "unittest", "discover", "-s", "tests",
                                      "-p", "test_original_regraph*.py"], contract["run_timeout_seconds"])
        contents = lambda step: Path(step["stdout"]).read_text()
        report["analysis"] = analyze_frontend(contents(first), contents(second), original, contract)
        report["gather_regression"] = analyze(
            contents(invariant), contents(comparison), contents(repeat), gather_contract)
        frozen = json.loads((root / "docs/experiments/comparisons/grasu_regraph_stage_validation/"
                             "finite_gather_results.json").read_text())
        if not same_typed(report["gather_regression"], frozen["analysis"]):
            raise ValueError("previously admitted Gather state/cycle/counter results changed")
        if [row["sha256"] for row in captured] != [row["sha256"] for row in frozen["source_captures"]]:
            raise ValueError("original source capture words changed from accepted Gather checkpoint")
        report["frozen_gather_and_captures_identical"] = True
        report["negative_controls"] = run_negative_controls(root, output, binaries[2], captured, gather_contract)
        if not all(row["expected_rejection"] for row in report["negative_controls"]):
            raise ValueError("source comparator corruption gate failed")
        report["binaries"].extend(sanitize_cases(root, output, compiler, execute,
            {"frontend": ("frontend_tests.cpp", [], contents(first))},
            contract["build_timeout_seconds"], contract["run_timeout_seconds"]))
        report["ubsan_identical_no_diagnostics"] = True
        if source_identities(root) != identities or sha256_file(contract_path) != report["contract_sha256"]:
            raise ValueError("tested source/contract changed during study")
        if sha256_file(gather_path) != report["gather_contract_sha256"]:
            raise ValueError("gather regression contract changed")
        if (admit_captures(captures, root, contract) != captured or
                admit_protocol(protocol, root, contract) != original):
            raise ValueError("original source evidence changed during study")
        if any(sha256_file(Path(item["path"])) != item["sha256"] for item in report["binaries"]):
            raise ValueError("tested binary changed during study")
        report["status"] = report["analysis"]["status"]
    except (ValueError, RuntimeError, OSError) as error:
        report["status"], report["error"] = "FAILED", str(error)
    atomic_write_json(output / "report.json", report)
    return report
