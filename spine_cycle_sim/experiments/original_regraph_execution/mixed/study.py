"""Fixed, bounded mixed original-R whole-graph functional/predicted timing study."""

import json
from pathlib import Path
import shutil
import subprocess

from spine_cycle_sim.experiments.campaign_runtime import atomic_write_json, sha256_file
from spine_cycle_sim.experiments.original_regraph_execution.study import source_identities
from spine_cycle_sim.experiments.original_regraph_validation.analysis import same_typed
from spine_cycle_sim.experiments.upstream_controls.execution import run_bounded
from .analysis import STATUS, analyze, matrix
from .preparation import admit, verify
from .regression import verify as legacy
from .instrumentation import verify as instrument
from .negative_controls import run as negatives


def identities(root: Path) -> list[dict]:
    paths = source_identities(root)
    paths += [{"path": name, "sha256": sha256_file(root / name)} for name in (
        "scripts/run_original_regraph_mixed.py", "tests/test_original_regraph_mixed.py")]
    return sorted(paths, key=lambda item: item["path"])


def run(root: Path, input_run: Path, baseline: Path, output: Path) -> dict:
    contract_path = root / "configs/experiments/original_regraph_mixed_execution_v1.json"
    contract = json.loads(contract_path.read_text()); compiler = shutil.which("g++")
    if compiler is None: raise ValueError("mixed execution requires G++")
    output.mkdir(parents=True, exist_ok=False); shutil.copyfile(contract_path, output / "contract.json")
    report = {"schema_version": 1, "status": "NOT_COMPLETED", "contract_sha256": sha256_file(contract_path),
        "evidence_class": contract["evidence_class"], "boundary": contract["boundary"], "not_claimed": contract["not_claimed"],
        "source_revision": subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=root, text=True).strip(),
        "source_identities": identities(root), "compiler_version": subprocess.check_output([compiler, "--version"], text=True),
        "worktree_status": subprocess.check_output(["git", "status", "--porcelain"], cwd=root, text=True).splitlines(),
        "legacy_baseline": str(baseline), "steps": [], "inputs": [], "binaries": [], "FPGA_cycles": None, "publication_error_pct": None,
        "cases": [{"id": item["id"], "status": "NOT_RUN", "runs": []} for item in contract["cases"]]}

    def execute(name, command, timeout, expected_failure=False):
        print(f"Starting {name} (mixed model prediction, not FPGA/publication timing)", flush=True)
        step = {"id": name, **run_bounded(command, root, output / name, timeout=timeout,
            memory_gib=contract["memory_limit_gib"], reserve_gib=contract["reserve_gib"])}
        report["steps"].append(step); atomic_write_json(output / "report.json", report)
        if step["timed_out"] or not expected_failure and step["exit_code"]: raise ValueError(name + " failed; bounded attempt retained")
        return step

    try:
        report["inputs"] = admit(root, input_run, output / "inputs")
        build = output / "build"
        execute("configure", ["cmake", "-S", str(root), "-B", str(build), "-DCMAKE_BUILD_TYPE=Release",
            "-DCMAKE_EXPORT_COMPILE_COMMANDS=ON", f"-DCMAKE_CXX_COMPILER={compiler}"], contract["build_timeout_seconds"])
        execute("build", ["cmake", "--build", str(build), f"-j{contract['build_jobs']}"], contract["build_timeout_seconds"])
        binary = build / "cpp/original_regraph_mixed_execution"
        report["binaries"].append({"path": str(binary), "sha256": sha256_file(binary)})
        execute("ctest", ["ctest", "--test-dir", str(build), "--output-on-failure"], contract["run_timeout_seconds"])
        report["legacy"] = legacy(root, build, output, baseline, input_run, contract, execute)
        for case, row in zip(contract["cases"], report["cases"], strict=True):
            row["status"] = "RUNNING"
            admitted = next(item for item in report["inputs"] if item["id"] == case["input"])
            for repeat in ("first", "repeat"):
                directory = output / case["id"] / repeat; directory.mkdir(parents=True)
                step = execute(case["id"] + "_" + repeat, [str(binary), admitted["directory"], str(directory),
                    str(case["state_parents"]), str(case["latency"]), str(int(case["reverse"])), str(contract["max_cycles"]), "1"],
                    contract["run_timeout_seconds"])
                result = analyze(Path(step["stdout"]).read_text(), directory, case, admitted, contract)
                if Path(step["stderr"]).read_text(): raise ValueError("mixed execution emitted runtime diagnostics")
                atomic_write_json(directory / "analysis.json", result)
                row["runs"].append({"directory": str(directory), "analysis": result, "sha256": sha256_file(directory / "analysis.json")})
            if not same_typed(row["runs"][0]["analysis"], row["runs"][1]["analysis"]): raise ValueError("mixed repetition changed result")
            row["status"] = STATUS
        report["analysis"] = matrix(report["cases"])
        report["negative_controls"] = negatives(binary, output, report["inputs"], contract, execute)
        report["binaries"].append(instrument(root, output, compiler, contract, report, execute))
        report["ubsan_identical_no_diagnostics"] = True
        verify(report["inputs"])
        if report["source_identities"] != identities(root) or sha256_file(contract_path) != report["contract_sha256"]:
            raise ValueError("mixed source/contract changed during execution")
        if any(sha256_file(Path(item["path"])) != item["sha256"] for item in report["binaries"]): raise ValueError("mixed binary changed")
        report["status"] = STATUS
    except (ValueError, RuntimeError, OSError, subprocess.SubprocessError) as error:
        report["status"], report["error"] = "FAILED", str(error)
        for row in report["cases"]:
            if row["status"] == "RUNNING": row["status"] = "FAILED"
    atomic_write_json(output / "report.json", report); return report
