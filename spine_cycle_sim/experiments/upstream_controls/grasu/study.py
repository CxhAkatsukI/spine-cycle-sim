"""Bounded original G kernel-path source study; no performance inference."""

import json
from pathlib import Path
import shutil
import subprocess

from spine_cycle_sim.experiments.campaign_runtime import atomic_write_json, sha256_file
from spine_cycle_sim.experiments.upstream_controls.execution import dependency_identities, run_bounded
from .analysis import STATUS, analyze
from .fixtures import NAMES
from .preparation import author_snapshot, compiler_command, identities, preserve, legacy_reference, validate_contract
from .validation import negative_controls


def run(root: Path, source: Path, include: Path, baseline: Path, output: Path) -> dict:
    contract_path = root / "configs/experiments/original_grasu_source_path_v1.json"
    contract = json.loads(contract_path.read_text()); compiler = shutil.which("g++")
    if compiler is None or not (include / "ap_int.h").is_file(): raise ValueError("G source control requires G++, Vitis HLS headers and GMP")
    validate_contract(contract)
    output.mkdir(parents=True, exist_ok=False); shutil.copyfile(contract_path, output / "contract.json")
    report = {"schema_version": 1, "status": "NOT_COMPLETED", "contract_sha256": sha256_file(contract_path),
        "source_revision": subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=root, text=True).strip(),
        "worktree_status": subprocess.check_output(["git", "status", "--porcelain"], cwd=root, text=True).splitlines(),
        "compiler_version": subprocess.check_output([compiler, "--version"], text=True),
        "evidence_class": contract["evidence_class"], "boundary": contract["boundary"], "not_claimed": contract["not_claimed"],
        "source_identities": identities(root), "author_source": author_snapshot(root, source),
        "baseline": str(baseline), "preservation": preserve(root, baseline), "steps": [], "binaries": [],
        "cases": [{"id": name, "status": "NOT_RUN", "runs": []} for name in NAMES],
        "device_cycles": None, "publication_error_pct": None}

    def execute(name, command, timeout):
        print("Starting " + name + " (original G source-functional, not timing)", flush=True)
        step = {"id": name, **run_bounded(command, root, output / name, timeout=timeout,
            memory_gib=contract["memory_limit_gib"], reserve_gib=contract["reserve_gib"])}
        report["steps"].append(step); atomic_write_json(output / "report.json", report)
        if step["timed_out"] or step["exit_code"]: raise ValueError(name + " failed; bounded attempt retained")
        return step

    try:
        for family in ("normal", "ubsan", "legacy"):
            directory = output / family; directory.mkdir()
            execute(family + "_compile", compiler_command(root, source, include, directory, compiler,
                instrumented=family == "ubsan", legacy=family == "legacy"), contract["compile_timeout_seconds"])
            report["binaries"].append({"path": str(directory / "probe"), "sha256": sha256_file(directory / "probe"),
                "dependencies": dependency_identities(directory / "dependencies.d", root)})
        for case, row in enumerate(report["cases"]):
            row["status"] = "RUNNING"
            for family, repeat in (("normal", "first"), ("normal", "repeat"), ("ubsan", "ubsan")):
                directory = output / row["id"] / repeat; directory.mkdir(parents=True)
                step = execute(row["id"] + "_" + repeat, [str(output / family / "probe"), str(case),
                    str(directory / "protocol.u32le"), str(directory / "state.u32le")], contract["run_timeout_seconds"])
                observed = analyze(directory, case, Path(step["stdout"]), Path(step["stderr"]))
                if row["runs"] and row["runs"][0]["analysis"] != observed: raise ValueError("G repeat/instrumented result changed")
                row["runs"].append({"directory": str(directory), "analysis": observed})
            row["status"] = STATUS
        reference = next(step for step in report["steps"] if step["id"] == "mixed_three_batches_first")
        report["negative_controls"] = negative_controls(output / "mixed_three_batches/first", Path(reference["stdout"]), Path(reference["stderr"]))
        legacy = execute("legacy_cache", [str(output / "legacy/probe")], contract["run_timeout_seconds"])
        for stream in ("stdout", "stderr"):
            if Path(legacy[stream]).read_bytes() != legacy_reference(root, stream):
                raise ValueError("G previous cache control changed")
        report["legacy_cache_stdout_sha256"] = sha256_file(Path(legacy["stdout"]))
        execute("focused_tests", ["python3", "-m", "unittest", "discover", "-s", "tests", "-p", "test_original_grasu_source_path.py"], contract["run_timeout_seconds"])
        report["preservation"] = preserve(root, baseline)
        if report["source_identities"] != identities(root) or report["author_source"] != author_snapshot(root, source):
            raise ValueError("G study/source identity changed while executing")
        for binary in report["binaries"]:
            for item in [binary, *binary["dependencies"]]:
                if sha256_file(Path(item["path"])) != item["sha256"]: raise ValueError("G compiled dependency changed")
        report["status"] = STATUS
    except (ValueError, RuntimeError, OSError, subprocess.SubprocessError) as error:
        report["status"], report["error"] = "FAILED", str(error)
        for row in report["cases"]:
            if row["status"] == "RUNNING": row["status"] = "FAILED"
    atomic_write_json(output / "report.json", report); return report
