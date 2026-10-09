"""Bounded existing-adapter source study, separate from future finite A4/B timing."""

import json
from pathlib import Path
import shutil
import subprocess

from spine_cycle_sim.experiments.campaign_runtime import atomic_write_json, sha256_file
from spine_cycle_sim.experiments.upstream_controls.execution import dependency_identities, run_bounded
from ..preparation import admit_inputs, verify_inputs
from .analysis import STATUS, analyze, inspect
from .preparation import prepare
from .regression import preserve, run as regress
from .validation import capture_negatives, input_negatives


def identities(root):
    paths = [root / name for name in ("scripts/run_original_regraph_adapter_source.py", "tests/test_original_regraph_adapter.py",
        "configs/experiments/original_regraph_adapter_source_v1.json", "cpp/tests/publication_sources/adapter_probe.cpp")]
    for directory, pattern in (("cpp/tests/publication_sources/adapter", "*.hpp"), ("spine_cycle_sim/experiments/original_regraph_execution/adapter", "*.py"),
            ("cpp/tests/original_regraph/whole_graph", "*.hpp")):
        paths.extend((root / directory).rglob(pattern))
    return [{"path": str(path.relative_to(root)), "sha256": sha256_file(path)} for path in sorted(set(paths))]


def command(root, include, output, compiler, defines, instrumented):
    flags = [compiler, "-std=c++20", "-O1", "-g0", "-D_GLIBCXX_ASSERTIONS", "-DDISABLE_MAX_HLS_STREAM_DEPTH_PRINT", "-Wno-unknown-pragmas", "-MD", "-MT", "probe", "-MF", str(output / "dependencies.d"),
        f"-I{include}", f"-I{include / 'etc'}", f"-I{output.parent / 'source'}"]
    flags += [f"-D{key}={value}" for key, value in defines.items()]
    if instrumented: flags += ["-fsanitize=undefined", "-fno-sanitize-recover=all"]
    return flags + [str(root / "cpp/tests/publication_sources/adapter_probe.cpp"), "-pthread", "-lgmp", "-o", str(output / "probe")]


def run(root: Path, adapter: Path, include: Path, input_run: Path, baseline: Path, output: Path):
    path = root / "configs/experiments/original_regraph_adapter_source_v1.json"; contract = json.loads(path.read_text())
    if sha256_file(adapter) != contract["adapter_source_sha256"]: raise ValueError("adapter source is not the pinned sharded destination-only revision")
    compiler = shutil.which("g++")
    if compiler is None or not (include / "ap_int.h").is_file(): raise ValueError("adapter source study needs G++ and real Vitis headers")
    output.mkdir(parents=True, exist_ok=False); shutil.copyfile(path, output / "contract.json")
    prepared = output / "source"; prepared.mkdir(); shutil.copyfile(adapter, prepared / "pma_to_regraph_adapter.cpp")
    report = {"schema_version": 1, "status": "NOT_COMPLETED", "evidence_class": contract["evidence_class"], "boundary": contract["boundary"],
        "not_claimed": contract["not_claimed"], "source_identities": identities(root), "contract_sha256": sha256_file(path), "adapter_sha256": sha256_file(adapter),
        "source_revision": subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=root, text=True).strip(), "compiler_version": subprocess.check_output([compiler, "--version"], text=True),
        "baseline": str(baseline), "preservation": preserve(root, baseline), "inputs": [], "binaries": [], "steps": [],
        "cases": [{"id": name, "status": "NOT_RUN", "runs": []} for name in contract["inputs"]], "device_cycles": None, "matched_A4_B_overhead": None}

    def execute(name, cmd, timeout=contract["run_timeout_seconds"], expected_code=0):
        print("Starting " + name + " (source function or exact A4 regression, not matched adapter timing)", flush=True)
        step = {"id": name, **run_bounded(cmd, root, output / name, timeout=timeout, memory_gib=contract["memory_limit_gib"], reserve_gib=contract["reserve_gib"])}
        report["steps"].append(step); atomic_write_json(output / "report.json", report)
        if step["timed_out"] or step["exit_code"] != expected_code: raise ValueError(name + " failed; raw attempt retained")
        return step

    try:
        report["inputs"] = admit_inputs(root, input_run, output / "inputs")
        if [row["id"] for row in report["inputs"]] != contract["inputs"]: raise ValueError("adapter full input matrix changed")
        for item in report["inputs"]:
            item["adapter_layout"] = prepare(Path(item["directory"])); inspect(Path(item["directory"]))
        for family in ("normal", "ubsan"):
            directory = output / family; directory.mkdir()
            execute("adapter_" + family + "_compile", command(root, include, directory, compiler, contract["defines"], family == "ubsan"), contract["compile_timeout_seconds"])
            report["binaries"].append({"path": str(directory / "probe"), "sha256": sha256_file(directory / "probe"), "dependencies": dependency_identities(directory / "dependencies.d", root)})
        for row in report["cases"]:
            row["status"] = "RUNNING"; item = next(item for item in report["inputs"] if item["id"] == row["id"])
            for suffix, family in (("first", "normal"), ("repeat", "normal"), ("ubsan", "ubsan")):
                directory = output / "captures" / row["id"] / suffix; directory.mkdir(parents=True)
                step = execute("adapter_" + row["id"] + "_" + suffix, [str(output / family / "probe"), item["directory"], str(directory)])
                value = analyze(Path(item["directory"]), directory, Path(step["stdout"]), Path(step["stderr"]))
                if row["runs"] and value != row["runs"][0]["analysis"]: raise ValueError("adapter full repetition/UBSan capture changed")
                row["runs"].append({"directory": str(directory), "analysis": value})
            row["status"] = STATUS
        boundary = next(item for item in report["inputs"] if item["id"] == "boundary_ring")
        report["input_negatives"] = input_negatives(output / "normal/probe", Path(boundary["directory"]), output, execute)
        step = next(item for item in report["steps"] if item["id"] == "adapter_boundary_ring_first")
        report["capture_negatives"] = capture_negatives(Path(boundary["directory"]), output / "captures/boundary_ring/first", Path(step["stdout"]), Path(step["stderr"]))
        report["wiring_regression"] = regress(root, baseline, output, report["inputs"], compiler, execute)
        execute("focused_tests", ["python3", "-m", "unittest", "discover", "-s", "tests", "-p", "test_original_regraph_adapter.py"], 180)
        verify_inputs(report["inputs"])
        for item in report["inputs"]:
            for field in item["adapter_layout"]["files"]:
                if sha256_file(Path(item["directory"]) / field["name"]) != field["sha256"]: raise ValueError("adapter input changed")
        for binary in report["binaries"] + report["wiring_regression"]["binaries"]:
            for field in [binary, *binary.get("dependencies", [])]:
                if sha256_file(Path(field["path"])) != field["sha256"]: raise ValueError("adapter dependency/binary changed")
        if identities(root) != report["source_identities"] or sha256_file(path) != report["contract_sha256"]: raise ValueError("adapter source/contract changed during study")
        if sha256_file(prepared / "pma_to_regraph_adapter.cpp") != contract["adapter_source_sha256"]: raise ValueError("adapter copied source changed")
        report["preservation"] = preserve(root, baseline); report["status"] = STATUS
    except (ValueError, OSError, RuntimeError, subprocess.SubprocessError) as error:
        report["status"], report["error"] = "FAILED", str(error)
        for row in report["cases"]:
            if row["status"] == "RUNNING": row["status"] = "FAILED"
    atomic_write_json(output / "report.json", report); return report
