"""Build in isolation, run finite-resource gates, and preserve every attempt."""

from __future__ import annotations

import json
from pathlib import Path
import shutil
import subprocess

from spine_cycle_sim.experiments.campaign_runtime import atomic_write_json, sha256_file
from spine_cycle_sim.experiments.upstream_controls.execution import run_bounded
from .analysis import admit_captures, analyze
from .negative_controls import run_negative_controls


def source_identities(root: Path) -> list[dict]:
    paths = {root / name for name in (
        "CMakeLists.txt", "cpp/CMakeLists.txt", "cpp/include/spine_sim/fifo.hpp",
        "cpp/include/spine_sim/component.hpp", "cpp/include/spine_sim/scheduler.hpp",
        "cpp/include/spine_sim/axi.hpp", "cpp/include/spine_sim/memory_backend.hpp",
        "cpp/src/axi.cpp", "cpp/src/memory_backend.cpp",
        "cpp/src/scheduler.cpp", "scripts/run_original_regraph_gather_validation.py",
        "scripts/run_original_regraph_frontend_validation.py",
        "tests/test_original_regraph_validation.py", "tests/test_original_regraph_frontend.py",
        "spine_cycle_sim/experiments/upstream_controls/execution.py",
        "spine_cycle_sim/experiments/campaign_runtime.py")}
    for directory in ("cpp/include/spine_sim/original_regraph", "cpp/src/original_regraph",
                      "cpp/tests/original_regraph",
                      "spine_cycle_sim/experiments/original_regraph_validation"):
        paths.update(path for path in (root / directory).rglob("*")
                     if path.suffix in (".hpp", ".cpp", ".py"))
    return [{"path": str(path.relative_to(root)), "sha256": sha256_file(path)}
            for path in sorted(paths)]


def run_study(root: Path, contract_path: Path, captures: Path, output: Path) -> dict:
    contract = json.loads(contract_path.read_text())
    # This is a fixed acceptance matrix, not a generic configurable benchmark.
    canonical = root / "configs/experiments/original_regraph_gather_validation_v1.json"
    if contract != json.loads(canonical.read_text()):
        raise ValueError("unsupported finite-component contract; declare a new reviewed matrix")
    admitted = admit_captures(captures, root, contract)
    output.mkdir(parents=True, exist_ok=False)
    shutil.copyfile(contract_path, output / "contract.json")
    identities = source_identities(root)
    compiler = shutil.which("c++")
    if compiler is None:
        raise ValueError("a C++ compiler is required")
    report = {
        "schema_version": 1, "evidence_class": contract["evidence_class"],
        "boundary": contract["boundary"], "contract_sha256": sha256_file(contract_path),
        "source_revision": subprocess.check_output(
            ["git", "rev-parse", "HEAD"], cwd=root, text=True).strip(),
        "worktree_status": subprocess.check_output(
            ["git", "status", "--porcelain"], cwd=root, text=True).splitlines(),
        "compiler_path": compiler,
        "compiler_version": subprocess.check_output([compiler, "--version"], text=True),
        "cmake_version": subprocess.check_output(["cmake", "--version"], text=True),
        "source_identities": identities, "source_captures": admitted, "steps": [],
        "not_claimed": contract["not_claimed"], "status": "NOT_COMPLETED",
    }
    limits = {"memory_gib": contract["memory_limit_gib"], "reserve_gib": contract["reserve_gib"]}
    build = output / "build"

    def execute(name: str, command: list[str], timeout: int) -> dict:
        print(f"Starting {name} (original Little gather boundary only)", flush=True)
        step = {"id": name, **run_bounded(command, root, output / name, timeout=timeout, **limits)}
        report["steps"].append(step)
        atomic_write_json(output / "report.json", report)
        if step["exit_code"] != 0 or step["timed_out"]:
            raise ValueError(f"{name} failed; preserved logs include any partial output")
        return step

    try:
        execute("configure", ["cmake", "-S", str(root), "-B", str(build),
                              "-DCMAKE_BUILD_TYPE=Release", "-DCMAKE_EXPORT_COMPILE_COMMANDS=ON",
                              f"-DCMAKE_CXX_COMPILER={compiler}"],
                contract["build_timeout_seconds"])
        execute("build", ["cmake", "--build", str(build), "--parallel",
                          str(contract["build_parallelism"])], contract["build_timeout_seconds"])
        binaries = [build / "cpp" / name for name in (
            "original_regraph_gather_tests", "original_regraph_source_comparison")]
        report["binaries"] = [{"path": str(path), "sha256": sha256_file(path)} for path in binaries]
        report["compile_commands_sha256"] = sha256_file(build / "compile_commands.json")
        report["cmake_cache_sha256"] = sha256_file(build / "CMakeCache.txt")
        invariants = execute("invariants", [str(binaries[0])], contract["run_timeout_seconds"])
        comparison_command = [str(binaries[1]), *[row["path"] for row in admitted]]
        comparison = execute("source_comparison", comparison_command, contract["run_timeout_seconds"])
        repeat = execute("source_comparison_repeat", comparison_command, contract["run_timeout_seconds"])
        execute("cpp_regression", ["ctest", "--test-dir", str(build), "--output-on-failure"],
                contract["run_timeout_seconds"])
        report["analysis"] = analyze(*[Path(row["stdout"]).read_text() for row in (
            invariants, comparison, repeat)], contract)
        report["negative_controls"] = run_negative_controls(root, output, binaries[1], admitted, contract)
        if not all(row["expected_rejection"] for row in report["negative_controls"]):
            raise ValueError("compiled comparator did not reject corrupted/truncated/excess capture")
        if source_identities(root) != identities or sha256_file(contract_path) != report["contract_sha256"]:
            raise ValueError("model/test/contract identity changed during validation")
        if admit_captures(captures, root, contract) != admitted:
            raise ValueError("original-source capture identity changed during validation")
        for row in report["binaries"]:
            if sha256_file(Path(row["path"])) != row["sha256"]:
                raise ValueError("tested binary changed during validation")
        report["status"] = report["analysis"]["status"]
    except (ValueError, RuntimeError, OSError) as error:
        report["status"] = "FAILED"
        report["error"] = str(error)
    atomic_write_json(output / "report.json", report)
    return report
