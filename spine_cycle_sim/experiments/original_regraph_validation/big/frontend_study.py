"""Bounded original Big source-memory/Scatter validation and old-result regression."""

import json
from pathlib import Path
import shutil
import struct
import subprocess

from spine_cycle_sim.experiments.campaign_runtime import atomic_write_json, sha256_file
from spine_cycle_sim.experiments.upstream_controls.execution import run_bounded
from spine_cycle_sim.experiments.original_regraph_validation.instrumentation import sanitize_cases
from .study import source_identities
from .frontend_sources import capture
from .frontend_analysis import STATUS, analyze
from .regression import verify_legacy


def identities(root: Path) -> list[dict]:
    result = source_identities(root)
    for name in ("scripts/run_original_regraph_big_frontend_validation.py", "tests/test_original_regraph_big_frontend.py",
                 "cpp/tests/publication_sources/regraph_big_frontend_probe.cpp", "spine_cycle_sim/experiments/upstream_controls/study.py"):
        if not any(row["path"] == name for row in result): result.append({"path": name, "sha256": sha256_file(root / name)})
    return sorted(result, key=lambda row: row["path"])


def run(root: Path, source: Path, hls: Path, baseline: Path, output: Path) -> dict:
    contract_path = root / "configs/experiments/original_regraph_big_frontend_validation_v1.json"
    contract = json.loads(contract_path.read_text())
    output.mkdir(parents=True, exist_ok=False)
    shutil.copyfile(contract_path, output / "contract.json")
    compiler = shutil.which("g++")
    if compiler is None or not (hls / "ap_int.h").is_file(): raise ValueError("G++ and Vitis headers are required")
    report = {"schema_version": 1, "status": "NOT_COMPLETED", "evidence_class": contract["evidence_class"],
        "boundary": contract["boundary"], "contract_sha256": sha256_file(contract_path), "steps": [], "binaries": [],
        "source_identities": identities(root), "compiler_version": subprocess.check_output([compiler, "--version"], text=True),
        "source_revision": subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=root, text=True).strip(),
        "worktree_status": subprocess.check_output(["git", "status", "--porcelain"], cwd=root, text=True).splitlines(),
        "not_claimed": contract["not_claimed"], "FPGA_cycles": None, "publication_error_pct": None}

    def execute(name, command, timeout, expected_failure=False):
        print(f"Starting {name} (Big memory/frontend timing predicted)", flush=True)
        row = {"id": name, **run_bounded(command, root, output / name, timeout=timeout,
            memory_gib=contract["memory_limit_gib"], reserve_gib=contract["reserve_gib"])}
        report["steps"].append(row); atomic_write_json(output / "report.json", report)
        if row["timed_out"] or not expected_failure and row["exit_code"] != 0: raise ValueError(f"{name} failed; attempt preserved")
        return row

    try:
        report["source_control"] = capture(root, source, hls, output, contract, compiler, execute)
        build = output / "build"
        execute("configure", ["cmake", "-S", str(root), "-B", str(build), "-DCMAKE_BUILD_TYPE=Release", "-DCMAKE_EXPORT_COMPILE_COMMANDS=ON"], contract["build_timeout_seconds"])
        execute("build", ["cmake", "--build", str(build), f"-j{contract['build_jobs']}"], contract["build_timeout_seconds"])
        expected = {}
        for name in ("big_frontend_tests", "big_frontend_comparison"):
            binary = build / "cpp" / ("original_regraph_" + name)
            report["binaries"].append({"path": str(binary), "sha256": sha256_file(binary)})
            args = [] if name.endswith("tests") else [report["source_control"]["capture"]["path"]]
            for suffix in ("first", "repeat"):
                row = execute(name + "_" + suffix, [str(binary), *args], contract["run_timeout_seconds"])
                text = Path(row["stdout"]).read_text()
                if Path(row["stderr"]).read_text(): raise ValueError("Big frontend emitted runtime diagnostics")
                analyze(text, contract, comparison=name.endswith("comparison"))
                if suffix == "first": expected[name] = text
                elif text != expected[name]: raise ValueError("Big frontend repeat changed counters")
            report[name] = analyze(expected[name], contract, comparison=name.endswith("comparison"))
        if [row["logical_requests"] + 1 for row in report["big_frontend_comparison"]] != [
                row["requests_including_end"] for row in report["source_control"]["cases"]]: raise ValueError("source request coverage mismatch")
        execute("ctest", ["ctest", "--test-dir", str(build), "--output-on-failure"], contract["run_timeout_seconds"])
        report["legacy"] = verify_legacy(root, build, output, baseline, contract, execute)
        old = json.loads((root / "docs/experiments/comparisons/grasu_regraph_stage_validation/big_gather_results.json").read_text())
        old_capture = old["source_control"]["capture"]
        if sha256_file(Path(old_capture["path"])) != old_capture["sha256"]: raise ValueError("frozen Big gather capture changed")
        row = execute("legacy_big_comparison", [str(build / "cpp/original_regraph_big_comparison"), old_capture["path"]], contract["run_timeout_seconds"])
        previous = next(row for row in old["steps"] if row["id"] == "big_comparison_first")
        if any(Path(row[key]).read_bytes() != Path(previous[key]).read_bytes() for key in ("stdout", "stderr")):
            raise ValueError("Big frontend addition changed complete Big Gather original-source comparison")
        report["legacy_big_comparison_identical"] = True
        report["negative_controls"] = []
        original = Path(report["source_control"]["capture"]["path"])
        payload = original.read_bytes()
        _id, _offset, _bursts, requests, responses = struct.unpack_from("<5I", payload, 16)
        edits = {"header": 0, "request": 36, "response": 36 + requests * 12 + 8,
                 "update": 36 + requests * 12 + responses * 72 + 4}
        for kind in (*edits, "truncated", "excess"):
            damaged = output / ("negative_" + kind + ".u32le")
            data = bytearray(payload)
            if kind in edits: data[edits[kind]] ^= 1
            elif kind == "truncated": del data[-4:]
            else: data += bytes(4)
            damaged.write_bytes(data)
            row = execute("negative_" + kind, [str(build / "cpp/original_regraph_big_frontend_comparison"), str(damaged)], contract["run_timeout_seconds"], True)
            if row["exit_code"] == 0: raise ValueError("damaged Big frontend capture accepted")
            report["negative_controls"].append({"id": kind, "rejected": True, "sha256": sha256_file(damaged)})
        report["binaries"] += sanitize_cases(root, output, compiler, execute, {
            name: (name + ".cpp", [] if name.endswith("tests") else [str(original)], text) for name, text in expected.items()},
            contract["build_timeout_seconds"], contract["run_timeout_seconds"])
        report["ubsan_identical_no_diagnostics"] = True
        if identities(root) != report["source_identities"] or sha256_file(contract_path) != report["contract_sha256"]:
            raise ValueError("Big frontend model/contract code changed during run")
        for item in report["source_control"]["dependencies"] + report["binaries"] + report["source_control"]["binaries"] + [report["source_control"]["capture"]]:
            if sha256_file(Path(item["path"])) != item["sha256"]: raise ValueError("Big frontend dependency/binary/capture changed")
        report["status"] = STATUS
    except (ValueError, RuntimeError, OSError, subprocess.SubprocessError) as error:
        report["status"], report["error"] = "FAILED", str(error)
    atomic_write_json(output / "report.json", report)
    return report
