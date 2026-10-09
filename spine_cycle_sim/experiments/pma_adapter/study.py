"""Bounded matched A4/B matrix with exact legacy regression and honest timeouts."""

import json
from pathlib import Path
import shutil
import subprocess
from threading import Lock

from spine_cycle_sim.experiments.campaign_runtime import atomic_write_json, sha256_file
from ..upstream_controls.execution import run_bounded
from ..original_regraph_execution.analysis import analyze as analyze_a4
from ..original_regraph_execution.preparation import verify_inputs
from . import analysis, conformance, preparation, schedules
from .execution import parallel, step_order


def identities(root):
    paths = [root / name for name in ("cpp/CMakeLists.txt", "CMakeLists.txt", "scripts/run_pma_regraph_control.py",
        "configs/experiments/pma_regraph_finite_control_v1.json", "tests/test_pma_regraph_control.py",
        "cpp/tests/publication_sources/adapter_routing_probe.cpp")]
    for directory in ("cpp/src", "cpp/include", "cpp/tests/original_regraph", "cpp/tests/pma_adapter",
            "cpp/tests/publication_sources/adapter", "spine_cycle_sim/experiments/pma_adapter",
            "spine_cycle_sim/experiments/original_regraph_execution/adapter"):
        paths.extend(path for path in (root / directory).rglob("*") if path.suffix in (".hpp", ".cpp", ".py"))
    return [{"path": str(path.relative_to(root)), "sha256": sha256_file(path)} for path in sorted(set(paths))]


def run(root: Path, source: Path, packet: Path, include: Path, input_run: Path, baseline: Path, output: Path):
    path = root / "configs/experiments/pma_regraph_finite_control_v1.json"
    contract = json.loads(path.read_text())
    if sha256_file(source) != contract["adapter_source_sha256"]:
        raise ValueError("finite PMA source differs from declared existing adapter")
    compiler = shutil.which("g++")
    if not compiler or not (include / "ap_int.h").is_file():
        raise ValueError("finite PMA control requires G++ and real Vitis headers")
    output.mkdir(parents=True, exist_ok=False)
    shutil.copyfile(path, output / "contract.json")
    (output / "source").mkdir()
    shutil.copyfile(source, output / "source/pma_to_regraph_adapter.cpp")
    old = json.loads((baseline / "baseline.json").read_text())
    if old["contract"]["cases"] != contract["cases"]:
        raise ValueError("finite PMA matrix differs from pre-edit A4")
    report = {"schema_version": 1, "status": "NOT_COMPLETED", "contract_sha256": sha256_file(path),
        "source_revision": subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=root, text=True).strip(),
        "source_identities": identities(root), "compiler_version": subprocess.check_output([compiler, "--version"], text=True),
        "baseline": str(baseline), "preservation": preparation.preserve(root, baseline), "inputs": [],
        "steps": [], "cases": [{"id": case["id"], "status": "NOT_RUN"} for case in contract["cases"]],
        "FPGA_measured_cycles": None, "publication_rate_error_pct": None, "evidence_class": contract["evidence_class"]}

    lock = Lock()

    def execute(name, command, timeout=contract["compile_timeout_seconds"], allow_terminal_failure=False):
        print("Starting " + name + " (finite prediction/source control, not FPGA/publication match)", flush=True)
        step = {"id": name, **run_bounded(command, root, output / name, timeout=timeout,
            memory_gib=contract["memory_limit_gib"], reserve_gib=contract["reserve_gib"])}
        with lock:
            report["steps"].append(step)
            atomic_write_json(output / "report.json", report)
        if not allow_terminal_failure and (step["timed_out"] or step["exit_code"]):
            raise ValueError(name + " failed; raw attempt preserved")
        return step

    try:
        report["schedules"] = schedules.inspect(packet, output / "schedules")
        report["inputs"] = preparation.inputs(root, input_run, baseline, output / "inputs")
        execute("configure", ["cmake", "-S", str(root), "-B", str(output / "build"), "-DCMAKE_BUILD_TYPE=Release", "-DCMAKE_EXPORT_COMPILE_COMMANDS=ON", f"-DCMAKE_CXX_COMPILER={compiler}"])
        execute("build", ["cmake", "--build", str(output / "build"), "-j2"])
        execute("ctest", ["ctest", "--test-dir", str(output / "build"), "--output-on-failure"], 300)
        report["conformance"] = conformance.run(root, output, include, compiler, execute)
        binaries = [output / "build/cpp" / name for name in ("original_regraph_a4_execution", "pma_regraph_execution", "pma_adapter_tests")]
        report["binaries"] = [{"path": str(binary), "sha256": sha256_file(binary)} for binary in binaries]
        for case, row, previous in zip(contract["cases"], report["cases"], old["cases"], strict=True):
            item = next(item for item in report["inputs"] if item["id"] == case["input"])
            args = [item["directory"], "", str(case["state_parents"]), str(case["latency"]), str(int(case["reverse"])), str(contract["max_cycles"])]
            row["status"] = "RUNNING"
            for label, extra in (("legacy", []), ("matched", [str(contract["input_parent_credits"])])):
                directory = output / label / case["id"]
                directory.mkdir(parents=True)
                args[1] = str(directory)
                step = execute(label + "_" + case["id"], [str(binaries[0]), *args, *extra], 300)
                stdout = Path(step["stdout"]).read_text()
                value = analyze_a4(stdout, directory, case, item, old["contract"])
                if label == "matched":
                    if value["result"].pop("input_parent_credits", None) != contract["input_parent_credits"]:
                        raise ValueError("matched compact A4 input credit budget differs")
                if value != previous["analysis"] or Path(step["stderr"]).read_text() or label == "legacy" and stdout != previous["stdout"]:
                    raise ValueError("legacy/matched A4 changed full pre-edit observations")
                row[label] = {"directory": str(directory), "analysis": value}
            row["status"] = "MATCHED_A4_ADMITTED_WAITING_PMA"
            atomic_write_json(output / "report.json", report)

        def finite(case):
            item = next(item for item in report["inputs"] if item["id"] == case["input"])
            row = next(row for row in report["cases"] if row["id"] == case["id"])
            with lock:
                row["status"] = "RUNNING"
                atomic_write_json(output / "report.json", report)
            directory = output / "finite" / case["id"]
            directory.mkdir(parents=True)
            args = [item["directory"], str(directory), str(case["state_parents"]), str(case["latency"]), str(int(case["reverse"])), str(contract["max_cycles"])]
            step = execute("pma_" + case["id"], [str(binaries[1]), *args], contract["run_timeout_seconds"], True)
            if step["timed_out"] or step["exit_code"]:
                return {"status": "TIMEOUT" if step["timed_out"] else "FAILED", "directory": str(directory)}
            value = analysis.analyze(Path(step["stdout"]).read_text(), Path(step["stderr"]).read_text(), directory, case, item, row["matched"]["analysis"], contract)
            return {"analysis": value, "directory": str(directory), "status": analysis.STATUS}

        for name, value in parallel([(case["id"], case) for case in contract["cases"]], finite, contract):
            with lock:
                next(row for row in report["cases"] if row["id"] == name).update(value)
                atomic_write_json(output / "report.json", report)
        report["instrumented_binary"] = conformance.compile_ubsan(root, output, compiler, execute)
        report["instrumented_cases"] = []
        for name in contract["instrumented_inputs"]:
            case = next(case for case in contract["cases"] if case["input"] == name)
            normal = next(row for row in report["cases"] if row["id"] == case["id"])
            if normal["status"] != analysis.STATUS:
                report["instrumented_cases"].append({"id": name, "status": "NOT_RUN_NORMAL_NOT_ADMITTED"})
                continue
            item = next(item for item in report["inputs"] if item["id"] == name)
            directory = output / "ubsan" / name
            directory.mkdir(parents=True)
            step = execute("ubsan_" + name, [report["instrumented_binary"]["path"], item["directory"], str(directory), str(case["state_parents"]), str(case["latency"]), "0", str(contract["max_cycles"])], contract["run_timeout_seconds"], True)
            value = None
            if not step["exit_code"] and not step["timed_out"]:
                value = analysis.analyze(Path(step["stdout"]).read_text(), Path(step["stderr"]).read_text(), directory, case, item, normal["matched"]["analysis"], contract)
                if value != normal["analysis"]:
                    raise ValueError("UBSan changed finite PMA full observations")
            report["instrumented_cases"].append({"id": name, "status": analysis.STATUS if value else "TIMEOUT" if step["timed_out"] else "FAILED", "directory": str(directory), "analysis": value})
        execute("focused_tests", ["python3", "-m", "unittest", "discover", "-s", "tests", "-p", "test_pma_regraph_control.py"], 180)
        steps = {step["id"]: step for step in report["steps"]}
        if len(steps) != len(report["steps"]):
            raise ValueError("finite PMA duplicate raw step")
        report["steps"] = [steps[name] for name in step_order(contract, report["instrumented_cases"])]
        verify_inputs(report["inputs"])
        for item in report["inputs"]:
            for field in item["adapter_layout"]["files"]:
                if sha256_file(Path(item["directory"]) / field["name"]) != field["sha256"]:
                    raise ValueError("finite PMA input changed")
        if report["source_identities"] != identities(root):
            raise ValueError("finite PMA source changed during execution")
        report["preservation"] = preparation.preserve(root, baseline)
        statuses = [row["status"] for row in report["cases"] + report["instrumented_cases"]]
        report["status"] = analysis.STATUS if all(status == analysis.STATUS for status in statuses) else "FINITE_A4_B_PARTIAL_MATRIX_NOT_ADMITTED"
        report["matrix_checks"] = analysis.check_matrix(report["cases"])
    except (ValueError, OSError, RuntimeError, subprocess.SubprocessError) as error:
        report["status"], report["error"] = "FAILED", str(error)
    atomic_write_json(output / "report.json", report)
    return report
