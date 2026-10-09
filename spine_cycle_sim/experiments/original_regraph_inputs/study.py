"""Execute the complete fixed author-host layout matrix with bounded resources."""

from __future__ import annotations

import json
from pathlib import Path
import shutil
import subprocess

from spine_cycle_sim.experiments.campaign_runtime import atomic_write_json, sha256_file
from spine_cycle_sim.experiments.original_regraph_validation.analysis import same_typed
from spine_cycle_sim.experiments.upstream_controls.execution import dependency_identities, run_bounded
from spine_cycle_sim.experiments.upstream_controls.sources import prepare_regraph, read_pins, verify_snapshot
from .analysis import STATUS, analyze_layout
from .preparation import compiler_command, inspect_graph, write_fixture
from .instrumentation import verify_instrumented


def source_identities(root: Path) -> list[dict]:
    paths = [root / name for name in ("scripts/run_original_regraph_inputs.py", "tests/test_original_regraph_inputs.py",
        "spine_cycle_sim/experiments/campaign_runtime.py", "spine_cycle_sim/experiments/upstream_controls/execution.py",
        "spine_cycle_sim/experiments/upstream_controls/sources.py",
        "spine_cycle_sim/experiments/original_regraph_validation/analysis.py")]
    paths.extend((root / "spine_cycle_sim/experiments/original_regraph_inputs").glob("*.py"))
    paths.extend((root / "cpp/tests/publication_sources").glob("regraph_layout*"))
    return [{"path": str(path.relative_to(root)), "sha256": sha256_file(path)} for path in sorted(paths)]


def run_study(root: Path, contract_path: Path, source_root: Path, output: Path,
              compiler: str, xrt_include: Path) -> dict:
    canonical = root / "configs/experiments/original_regraph_inputs_v1.json"
    contract = json.loads(contract_path.read_text())
    if not same_typed(contract, json.loads(canonical.read_text())):
        raise ValueError("unsupported original-host input matrix; declare a reviewed contract")
    if not (xrt_include / "CL/cl_ext_xilinx.h").is_file():
        raise ValueError("real XRT OpenCL extension headers required; no fake device API")
    pins = read_pins(root / "docs/experiments/comparisons/grasu_regraph_stage_validation/source_pins.json")
    original = source_root / "regraph"
    snapshot = verify_snapshot(original, pins["regraph"])
    output.mkdir(parents=True, exist_ok=False)
    shutil.copyfile(contract_path, output / "contract.json")
    identities = source_identities(root)
    report = {
        "schema_version": 1, "status": "NOT_COMPLETED", "evidence_class": contract["evidence_class"],
        "contract_sha256": sha256_file(contract_path), "source_revision": subprocess.check_output(
            ["git", "rev-parse", "HEAD"], cwd=root, text=True).strip(),
        "worktree_status": subprocess.check_output(["git", "status", "--porcelain"], cwd=root, text=True).splitlines(),
        "source_snapshot": snapshot, "source_identities": identities,
        "compiler_version": subprocess.check_output([compiler, "--version"], text=True),
        "inputs": [], "steps": [], "topologies": [],
        "cases": [{"id": f"{topology['id']}_{item['id']}", "status": "NOT_RUN", "runs": []}
                  for topology in contract["topologies"] for item in contract["inputs"]],
        "device_cycles": None, "publication_rate_error_pct": None, "not_claimed": contract["not_claimed"],
    }

    def execute(name, command, timeout):
        print(f"Starting {name} (original host input preparation only)", flush=True)
        step = {"id": name, **run_bounded(command, root, output / name, timeout=timeout,
            memory_gib=contract["memory_limit_gib"], reserve_gib=contract["reserve_gib"])}
        report["steps"].append(step)
        atomic_write_json(output / "report.json", report)
        if step["exit_code"] != 0 or step["timed_out"]:
            raise ValueError(f"{name} failed; bounded raw attempt retained")
        return step

    try:
        fixtures = output / "inputs"
        fixtures.mkdir()
        for item in contract["inputs"]:
            path = original / item["source_path"] if "source_path" in item else fixtures / f"{item['id']}.edges"
            if "fixture" in item:
                write_fixture(item["fixture"], path)
            graph = inspect_graph(path)
            if (any(graph[key] != item[key] for key in ("vertices", "logical_edges")) or
                    "sha256" in item and graph["sha256"] != item["sha256"]):
                raise ValueError("original input identity/count differs from declared fixture or graph")
            report["inputs"].append({"id": item["id"], **graph})
        for topology in contract["topologies"]:
            top = output / topology["id"]
            top.mkdir()
            prepared = top / "prepared"
            generated = prepare_regraph(original, prepared, topology["little"], topology["big"], contract["generator_python"])
            command = compiler_command(root, prepared, topology, top, compiler, xrt_include)
            execute(topology["id"] + "_compile", command, contract["compile_timeout_seconds"])
            dependencies = dependency_identities(top / "dependencies.d", root)
            binary = top / "probe"
            report["topologies"].append({**topology, "prepared": generated, "dependencies": dependencies,
                                          "binary_sha256": sha256_file(binary)})
            for graph in report["inputs"]:
                case = next(row for row in report["cases"] if row["id"] == f"{topology['id']}_{graph['id']}")
                case["status"] = "RUNNING"
                for repetition in ("first", "repeat"):
                    capture = top / graph["id"] / repetition
                    capture.mkdir(parents=True)
                    step = execute(case["id"] + "_" + repetition, [str(binary), graph["path"], str(capture),
                        str(contract["seed"]), str(topology["dense_partitions_argument"])], contract["run_timeout_seconds"])
                    result = analyze_layout(Path(step["stdout"]).read_text(), capture, topology, graph, contract)
                    atomic_write_json(capture / "layout.json", result)
                    case["runs"].append({"directory": str(capture), "layout_sha256": sha256_file(capture / "layout.json"),
                                          "analysis": result})
                if not same_typed(case["runs"][0]["analysis"], case["runs"][1]["analysis"]):
                    raise ValueError("original layout repetition changed graph/task/property capture")
                case["repeat_all_captures_identical"] = True
                case["status"] = STATUS
            if sha256_file(binary) != report["topologies"][-1]["binary_sha256"]:
                raise ValueError("original layout binary changed during matrix")
            for item in dependencies:
                if sha256_file(Path(item["path"])) != item["sha256"]:
                    raise ValueError("original layout source/header changed during matrix")
        report["instrumented_binaries"] = verify_instrumented(root, output, compiler, xrt_include, report, contract, execute)
        report["ubsan_identical_no_diagnostics"] = True
        if source_identities(root) != identities or sha256_file(contract_path) != report["contract_sha256"]:
            raise ValueError("original layout model/probe/contract changed during matrix")
        for graph in report["inputs"]:
            if sha256_file(Path(graph["path"])) != graph["sha256"]:
                raise ValueError("original input changed during matrix")
        if verify_snapshot(original, pins["regraph"]) != snapshot:
            raise ValueError("original author snapshot changed")
        report["status"] = STATUS
    except (ValueError, RuntimeError, OSError, subprocess.SubprocessError) as error:
        report["status"], report["error"] = "FAILED", str(error)
        for case in report["cases"]:
            if case["status"] == "RUNNING":
                case["status"], case["error"] = "FAILED", str(error)
    atomic_write_json(output / "report.json", report)
    return report
