"""Extend the admitted frontend regression with PR Apply and resident state."""

from __future__ import annotations

import json
from pathlib import Path
import shutil
import subprocess

from spine_cycle_sim.experiments.campaign_runtime import atomic_write_json, sha256_file
from spine_cycle_sim.experiments.upstream_controls.execution import run_bounded
from .analysis import same_typed
from .frontend_study import run_frontend_study
from .instrumentation import sanitize_cases
from .negative_controls import run_negative_controls
from .state_analysis import STATUS, analyze_state
from .state_sources import admit_apply
from .study import source_identities


def run_state_study(root: Path, contract_path: Path, captures: Path, protocol: Path,
                    apply_captures: Path, output: Path) -> dict:
    canonical = root / "configs/experiments/original_regraph_state_validation_v1.json"
    contract = json.loads(contract_path.read_text())
    if not same_typed(contract, json.loads(canonical.read_text())):
        raise ValueError("unsupported state matrix; declare a new reviewed contract")
    admitted = admit_apply(apply_captures, root, contract)
    output.mkdir(parents=True, exist_ok=False)
    shutil.copyfile(contract_path, output / "contract.json")
    identities = source_identities(root)
    report = {
        "schema_version": 1, "status": "NOT_COMPLETED", "evidence_class": contract["evidence_class"],
        "boundary": contract["boundary"], "contract_sha256": sha256_file(contract_path),
        "source_revision": subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=root, text=True).strip(),
        "worktree_status": subprocess.check_output(["git", "status", "--porcelain"], cwd=root, text=True).splitlines(),
        "source_identities": identities, "source_captures": admitted, "steps": [], "binaries": [],
        "not_claimed": contract["not_claimed"],
    }

    def execute(name, command, timeout):
        print(f"Starting {name} (original PR state model, not FPGA timing)", flush=True)
        step = {"id": name, **run_bounded(command, root, output / name, timeout=timeout,
                memory_gib=contract["memory_limit_gib"], reserve_gib=contract["reserve_gib"])}
        report["steps"].append(step)
        atomic_write_json(output / "report.json", report)
        if step["exit_code"] != 0 or step["timed_out"]:
            raise ValueError(f"{name} failed; raw output retained")
        return step

    try:
        frontend = run_frontend_study(root, root / "configs/experiments/original_regraph_frontend_validation_v1.json",
                                      captures, protocol, output / "frontend_regression")
        if frontend["status"] != "FINITE_MEMORY_FRONTEND_FUNCTIONAL_PASS_TIMING_PREDICTED":
            raise ValueError("frontend/Gather regression failed; see its saved report")
        frozen = root / "docs/experiments/comparisons/grasu_regraph_stage_validation/frontend_results.json"
        if not same_typed(frontend["analysis"], json.loads(frozen.read_text())["analysis"]):
            raise ValueError("previously accepted frontend cycles/counters changed")
        report["frontend_regression"] = {
            "report": str(output / "frontend_regression/report.json"),
            "sha256": sha256_file(output / "frontend_regression/report.json"),
            "accepted_frontend_results_sha256": sha256_file(frozen),
            "analysis_identical": True, "gather_and_source_captures_identical": True,
        }
        build = output / "frontend_regression/build/cpp"
        arguments = [row["path"] for row in admitted]
        cases = {"state": ("state_tests.cpp", []), "comparison": ("state_comparison.cpp", arguments),
                 "iterations": ("iteration_tests.cpp", [])}
        texts, repeated = {}, {}
        for name, (source, args) in cases.items():
            target = {"state": "state_tests", "comparison": "state_comparison", "iterations": "iteration_tests"}[name]
            binary = build / f"original_regraph_{target}"
            report["binaries"].append({"path": str(binary), "sha256": sha256_file(binary)})
            for suffix, collection in (("", texts), ("_repeat", repeated)):
                step = execute(name + suffix, [str(binary), *args], contract["run_timeout_seconds"])
                collection[name] = Path(step["stdout"]).read_text()
        report["analysis"] = analyze_state(texts["state"], texts["comparison"], texts["iterations"], repeated, contract)
        report["negative_controls"] = run_negative_controls(root, output, build / "original_regraph_state_comparison",
            admitted, contract, diagnostics=("differs from original Apply/writer source",
                                             "truncated original Apply capture", "excess original Apply capture words"))
        if not all(row["expected_rejection"] for row in report["negative_controls"]):
            raise ValueError("original Apply negative-reference gate failed")
        sanitized = {name: (source, args, texts[name]) for name, (source, args) in cases.items()}
        report["binaries"].extend(sanitize_cases(root, output, frontend["compiler_path"], execute, sanitized,
                                  contract["build_timeout_seconds"], contract["run_timeout_seconds"]))
        report["ubsan_identical_no_diagnostics"] = True
        if source_identities(root) != identities or sha256_file(contract_path) != report["contract_sha256"]:
            raise ValueError("state model/test/contract changed during study")
        if admit_apply(apply_captures, root, contract) != admitted:
            raise ValueError("original Apply evidence changed during study")
        if any(sha256_file(Path(row["path"])) != row["sha256"] for row in report["binaries"]):
            raise ValueError("tested state binary changed during study")
        report["status"] = STATUS
    except (ValueError, RuntimeError, OSError) as error:
        report["status"], report["error"] = "FAILED", str(error)
    atomic_write_json(output / "report.json", report)
    return report
