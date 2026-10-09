"""Bounded host/source composition with explicit compatibility and rejection gates."""

import json
from pathlib import Path
import shutil
import subprocess

from spine_cycle_sim.experiments.campaign_runtime import atomic_write_json, sha256_file
from spine_cycle_sim.experiments.upstream_controls.execution import dependency_identities, run_bounded
from ..preparation import author_snapshot, preserve
from .analysis import STATUS, analyze
from .fixtures import NAMES, read, write
from .preparation import compiler_command, identities, prepare, validate
from .regression import run as legacy
from .validation import bounds_negatives, capture_negatives, input_negatives


def run(root: Path, source: Path, include: Path, xrt: Path, baseline: Path, output: Path):
    path = root / "configs/experiments/original_grasu_host_v1.json"; contract = json.loads(path.read_text()); validate(contract)
    compiler = shutil.which("g++")
    if compiler is None or not (include / "ap_int.h").is_file() or not (xrt / "CL/cl_ext_xilinx.h").is_file():
        raise ValueError("G host control requires G++, real Vitis/XRT headers and GMP/OpenCL")
    output.mkdir(parents=True, exist_ok=False); shutil.copyfile(path, output / "contract.json")
    report = {"schema_version": 1, "status": "NOT_COMPLETED", "evidence_class": contract["evidence_class"], "boundary": contract["boundary"],
        "not_claimed": contract["not_claimed"], "contract_sha256": sha256_file(path), "source_identities": identities(root),
        "source_revision": subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=root, text=True).strip(),
        "worktree_status": subprocess.check_output(["git", "status", "--porcelain"], cwd=root, text=True).splitlines(),
        "compiler_version": subprocess.check_output([compiler, "--version"], text=True), "baseline": str(baseline),
        "preservation": preserve(root, baseline), "author_source": author_snapshot(root, source), "inputs": [], "binaries": [], "steps": [],
        "cases": [{"id": name, "status": "NOT_RUN", "runs": []} for name in NAMES], "device_cycles": None, "publication_error_pct": None}

    def execute(name, command, *, compile=False, expected_code=0):
        print("Starting " + name + " (guarded original host/source functional control, not timing)", flush=True)
        step = {"id": name, **run_bounded(command, root, output / name,
            timeout=contract["compile_timeout_seconds" if compile else "run_timeout_seconds"],
            memory_gib=contract["memory_limit_gib"], reserve_gib=contract["reserve_gib"])}
        report["steps"].append(step); atomic_write_json(output / "report.json", report)
        if step["timed_out"] or step["exit_code"] != expected_code: raise ValueError(name + " returned unexpected status; attempt retained")
        return step

    try:
        inputs = output / "inputs"; inputs.mkdir()
        for name in NAMES:
            input_path = inputs / (name + ".txt"); write(name, input_path)
            n, old, updates, final = read(input_path)
            report["inputs"].append({"id": name, "path": str(input_path), "sha256": sha256_file(input_path),
                "bytes": input_path.stat().st_size, "vertices": n, "initial_edges": len(old), "updates": len(updates), "final_edges": len(final)})
        report["variants"] = prepare(root, source, output / "prepared", contract); binaries = {}
        for family in ("original", "row_guard", "both_guards", "ubsan"):
            directory = output / family; directory.mkdir()
            prepared = output / "prepared" / ("both_guards" if family == "ubsan" else family)
            execute(family + "_compile", compiler_command(root, source, prepared, include, xrt, directory, compiler, family == "ubsan"), compile=True)
            binaries[family] = directory / "probe"
            report["binaries"].append({"path": str(binaries[family]), "sha256": sha256_file(binaries[family]),
                "dependencies": dependency_identities(directory / "dependencies.d", root)})
        report["original_bounds_failures"] = bounds_negatives(binaries, inputs / "empty_batch.txt", output, execute)
        for row in report["cases"]:
            row["status"] = "RUNNING"
            for suffix, family in (("first", "both_guards"), ("repeat", "both_guards"), ("ubsan", "ubsan")):
                directory = output / "captures" / row["id"] / suffix; directory.mkdir(parents=True)
                step = execute(row["id"] + "_" + suffix, [str(binaries[family]), str(inputs / (row["id"] + ".txt")), str(directory)])
                observed = analyze(inputs / (row["id"] + ".txt"), directory, Path(step["stdout"]), Path(step["stderr"]))
                if row["runs"] and row["runs"][0]["analysis"] != observed: raise ValueError("G host repeated/instrumented state changed")
                row["runs"].append({"directory": str(directory), "analysis": observed})
            row["status"] = STATUS
        report["input_negatives"] = input_negatives(binaries["both_guards"], output, execute)
        step = next(item for item in report["steps"] if item["id"] == "mixed_reservation_first")
        report["capture_negatives"] = capture_negatives(inputs / "mixed_reservation.txt", output / "captures/mixed_reservation/first", Path(step["stdout"]), Path(step["stderr"]))
        report["legacy"] = legacy(root, source, include, compiler, output, execute)
        execute("focused_tests", ["python3", "-m", "unittest", "discover", "-s", "tests", "-p", "test_original_grasu_host.py"])
        report["preservation"] = preserve(root, baseline)
        if report["source_identities"] != identities(root) or report["author_source"] != author_snapshot(root, source): raise ValueError("G host source changed during run")
        for item in report["inputs"]:
            if sha256_file(Path(item["path"])) != item["sha256"]: raise ValueError("G input changed during run")
        for binary in report["binaries"] + [report["legacy"]["binary"]]:
            for item in [binary, *binary["dependencies"]]:
                if sha256_file(Path(item["path"])) != item["sha256"]: raise ValueError("G binary/dependency changed during run")
        report["status"] = STATUS
    except (ValueError, RuntimeError, OSError, subprocess.SubprocessError) as error:
        report["status"], report["error"] = "FAILED", str(error)
        for row in report["cases"]:
            if row["status"] == "RUNNING": row["status"] = "FAILED"
    atomic_write_json(output / "report.json", report); return report
