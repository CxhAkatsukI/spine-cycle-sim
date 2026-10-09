"""Bounded fixed whole-A4 study; distinct from production SST and publication matching."""

from __future__ import annotations

import json
from pathlib import Path
import shutil
import subprocess

from spine_cycle_sim.experiments.campaign_runtime import atomic_write_json, sha256_file
from spine_cycle_sim.experiments.original_regraph_validation.analysis import same_typed
from spine_cycle_sim.experiments.upstream_controls.execution import run_bounded
from .analysis import STATUS, analyze, analyze_matrix
from .preparation import admit_inputs, verify_inputs
from .instrumentation import verify_instrumented
from .regression import verify_legacy
from .resource_evidence import admit_axi_evidence
from .negative_controls import run_negative_controls


def source_identities(root: Path) -> list[dict]:
    paths = [root / name for name in ("CMakeLists.txt", "cpp/CMakeLists.txt", "scripts/run_original_regraph_a4.py",
        "tests/test_original_regraph_execution.py", "spine_cycle_sim/experiments/campaign_runtime.py",
        "spine_cycle_sim/experiments/upstream_controls/execution.py",
        "spine_cycle_sim/experiments/upstream_controls/validation.py",
        "spine_cycle_sim/experiments/original_regraph_validation/analysis.py",
        "spine_cycle_sim/experiments/original_regraph_validation/state_sources.py")]
    for directory, pattern in (("cpp/include/spine_sim", "*.hpp"), ("cpp/src", "*.cpp"),
            ("cpp/tests/original_regraph", "*.hpp"), ("cpp/tests/original_regraph", "*.cpp"),
            ("spine_cycle_sim/experiments/original_regraph_inputs", "*.py"),
            ("spine_cycle_sim/experiments/original_regraph_execution", "*.py")):
        paths.extend((root / directory).rglob(pattern))
    return [{"path": str(path.relative_to(root)), "sha256": sha256_file(path)} for path in sorted(set(paths))]


def run_study(root: Path, contract_path: Path, input_run: Path, baseline: Path, output: Path,
              gather_captures: Path | None = None, apply_captures: Path | None = None) -> dict:
    contract = json.loads(contract_path.read_text())
    canonical = root / "configs/experiments/original_regraph_a4_execution_v1.json"
    if not same_typed(contract, json.loads(canonical.read_text())):
        raise ValueError("declare a reviewed whole-A4 contract instead of relaxing this matrix")
    output.mkdir(parents=True, exist_ok=False)
    shutil.copyfile(contract_path, output / "contract.json")
    identities = source_identities(root)
    compiler = shutil.which("g++")
    if compiler is None:
        raise ValueError("whole-A4 study requires an explicit available G++ compiler")
    report = {"schema_version": 1, "status": "NOT_COMPLETED", "evidence_class": contract["evidence_class"],
        "boundary": contract["boundary"], "contract_sha256": sha256_file(contract_path),
        "legacy_baseline": str(baseline),
        "source_identities": identities, "source_revision": subprocess.check_output(
            ["git", "rev-parse", "HEAD"], cwd=root, text=True).strip(),
        "worktree_status": subprocess.check_output(["git", "status", "--porcelain"], cwd=root, text=True).splitlines(),
        "steps": [], "inputs": [], "binaries": [], "not_claimed": contract["not_claimed"],
        "cases": [{"id": case["id"], "status": "NOT_RUN", "runs": []} for case in contract["cases"]],
        "FPGA_measured_cycles": None, "publication_rate_error_pct": None}
    report["compiler_path"] = compiler
    report["compiler_version"] = subprocess.check_output([compiler, "--version"], text=True)

    def execute(name, command, timeout, expected_failure=False):
        print(f"Starting {name} (whole A4 timing predicted, not FPGA)", flush=True)
        step = {"id": name, **run_bounded(command, root, output / name, timeout=timeout,
            memory_gib=contract["memory_limit_gib"], reserve_gib=contract["reserve_gib"])}
        report["steps"].append(step)
        atomic_write_json(output / "report.json", report)
        if step["timed_out"] or not expected_failure and step["exit_code"] != 0:
            raise ValueError(f"{name} failed; full attempt retained")
        return step

    try:
        report["axi_interface_evidence"] = admit_axi_evidence(root, contract)
        report["inputs"] = admit_inputs(root, input_run, output / "inputs")
        build = output / "build"
        execute("configure", ["cmake", "-S", str(root), "-B", str(build), "-DCMAKE_BUILD_TYPE=Release",
            "-DCMAKE_EXPORT_COMPILE_COMMANDS=ON", f"-DCMAKE_CXX_COMPILER={compiler}"], contract["build_timeout_seconds"])
        execute("build", ["cmake", "--build", str(build), f"-j{contract['build_jobs']}"], contract["build_timeout_seconds"])
        binary = build / "cpp/original_regraph_a4_execution"
        report["binaries"].append({"path": str(binary), "sha256": sha256_file(binary)})
        execute("ctest", ["ctest", "--test-dir", str(build), "--output-on-failure"], contract["run_timeout_seconds"])
        report["legacy_regression"] = verify_legacy(root, build, baseline, contract, execute, gather_captures, apply_captures)
        for case in contract["cases"]:
            row = next(row for row in report["cases"] if row["id"] == case["id"])
            row["status"] = "RUNNING"
            admitted = next(item for item in report["inputs"] if item["id"] == case["input"])
            for repetition in ("first", "repeat"):
                directory = output / case["id"] / repetition
                directory.mkdir(parents=True)
                command = [str(binary), admitted["directory"], str(directory), str(case["state_parents"]),
                           str(case["latency"]), str(int(case["reverse"])), str(contract["max_cycles"])]
                step = execute(case["id"] + "_" + repetition, command, contract["run_timeout_seconds"])
                result = analyze(Path(step["stdout"]).read_text(), directory, case, admitted, contract)
                if Path(step["stderr"]).read_text():
                    raise ValueError("whole A4 emitted unexpected runtime diagnostics")
                atomic_write_json(directory / "analysis.json", result)
                row["runs"].append({"directory": str(directory), "analysis": result,
                                     "analysis_sha256": sha256_file(directory / "analysis.json")})
            if not same_typed(row["runs"][0]["analysis"], row["runs"][1]["analysis"]):
                raise ValueError("whole A4 repetition changed values, cycles or counters")
            row["status"] = STATUS
        report["analysis"] = analyze_matrix(report["cases"])
        report["negative_controls"] = run_negative_controls(binary, output,
            next(item for item in report["inputs"] if item["id"] == "boundary_ring"), contract, execute)
        report["binaries"].append(verify_instrumented(root, output, compiler, contract, report, execute))
        report["ubsan_identical_no_diagnostics"] = True
        verify_inputs(report["inputs"])
        if admit_axi_evidence(root, contract) != report["axi_interface_evidence"]:
            raise ValueError("original HLS AXI evidence changed during execution")
        if source_identities(root) != identities or sha256_file(contract_path) != report["contract_sha256"]:
            raise ValueError("whole A4 source or contract changed during study")
        if any(sha256_file(Path(item["path"])) != item["sha256"] for item in report["binaries"]):
            raise ValueError("whole A4 binary changed during study")
        report["status"] = STATUS
    except (ValueError, OSError, RuntimeError, subprocess.SubprocessError) as error:
        report["status"], report["error"] = "FAILED", str(error)
        for row in report["cases"]:
            if row["status"] == "RUNNING":
                row["status"], row["error"] = "FAILED", str(error)
    atomic_write_json(output / "report.json", report)
    return report
