"""Recheck full A4 execution evidence and package logs with large-capture indexes."""

from __future__ import annotations

import json
from pathlib import Path
import shutil
import tarfile

from spine_cycle_sim.experiments.campaign_runtime import atomic_write_json, sha256_file
from spine_cycle_sim.experiments.original_regraph_validation.analysis import same_typed
from .analysis import STATUS, analyze, analyze_matrix
from .preparation import verify_inputs
from .resource_evidence import admit_axi_evidence
from .study import source_identities


def deliver(root: Path, run: Path, destination: Path, attempts: list[Path]) -> dict:
    report = json.loads((run / "report.json").read_text())
    contract = json.loads((run / "contract.json").read_text())
    canonical = json.loads((root / "configs/experiments/original_regraph_a4_execution_v1.json").read_text())
    if (not same_typed(contract, canonical) or sha256_file(run / "contract.json") != report["contract_sha256"] or
            report["status"] != STATUS or source_identities(root) != report["source_identities"] or
            report.get("ubsan_identical_no_diagnostics") is not True or
            report["legacy_regression"].get("default_component_and_full_source_comparison_outputs_identical") is not True or
            [item["id"] for item in report["negative_controls"]] != ["header", "assignment", "source", "arithmetic", "edge_value", "truncated"] or
            not all(item["expected_rejection"] is True for item in report["negative_controls"])):
        raise ValueError("whole A4 delivery requires a complete unchanged checkpoint")
    if ([case["id"] for case in report["cases"]] != [case["id"] for case in contract["cases"]] or
            [item["id"] for item in report["inputs"]] != ["boundary_ring", "skewed_sources", "amazon"] or
            len(report["binaries"]) != 2):
        raise ValueError("whole A4 delivery is missing declared cases, inputs or instrumentation")
    verify_inputs(report["inputs"])
    if admit_axi_evidence(root, contract) != report["axi_interface_evidence"]:
        raise ValueError("whole A4 original AXI evidence changed")
    steps = {step["id"]: step for step in report["steps"]}
    if len(steps) != len(report["steps"]):
        raise ValueError("duplicate whole A4 execution steps")
    negatives = {"negative_" + item["id"]: item for item in report["negative_controls"]}
    for step in steps.values():
        if step["timed_out"] or step["exit_code"] != (1 if step["id"] in negatives else 0):
            raise ValueError("whole A4 execution contains an unexpected failed step")
        if step["id"] in negatives and negatives[step["id"]]["diagnostic"] not in Path(step["stderr"]).read_text():
            raise ValueError("whole A4 negative-reference diagnostic changed")
    if not set(negatives).issubset(steps) or not {"configure", "build", "ctest", "ubsan_compile"}.issubset(steps):
        raise ValueError("whole A4 build, regression or rejection steps missing")
    baseline_path = Path(report["legacy_baseline"]) / "baseline.json"
    if sha256_file(baseline_path) != report["legacy_regression"]["baseline_sha256"]:
        raise ValueError("whole A4 legacy baseline changed")
    baseline = json.loads(baseline_path.read_text())
    for item in report["legacy_regression"]["results"]:
        step = steps["legacy_" + item["target"]]
        if sha256_file(Path(step["stdout"])) != item["stdout_sha256"]:
            raise ValueError("whole A4 legacy regression output changed")
        old = next((row for row in baseline["runs"] if row["target"] == item["target"]), None)
        old_step = old if old is not None else steps["old_" + item["target"]]
        if (Path(old_step["stdout"]).read_bytes() != Path(step["stdout"]).read_bytes() or
                Path(old_step["stderr"]).read_bytes() != Path(step["stderr"]).read_bytes()):
            raise ValueError("whole A4 old/new regression equality no longer holds")
        for capture in item.get("original_captures", []):
            if sha256_file(Path(capture["path"])) != capture["sha256"]:
                raise ValueError("whole A4 original regression capture changed")
    for binary in report["binaries"]:
        if sha256_file(Path(binary["path"])) != binary["sha256"]:
            raise ValueError("whole A4 tested binary changed")
        for item in binary.get("dependencies", []):
            if sha256_file(Path(item["path"])) != item["sha256"]:
                raise ValueError("whole A4 instrumented header changed")
    for case, observed in zip(contract["cases"], report["cases"], strict=True):
        if observed["status"] != STATUS or len(observed["runs"]) != 2:
            raise ValueError("whole A4 case incomplete")
        admitted = next(item for item in report["inputs"] if item["id"] == case["input"])
        for repetition, result in zip(("first", "repeat"), observed["runs"], strict=True):
            directory = Path(result["directory"])
            step = steps[case["id"] + "_" + repetition]
            if (step["exit_code"] or step["timed_out"] or Path(step["stderr"]).read_text() or
                    sha256_file(directory / "analysis.json") != result["analysis_sha256"] or
                    not same_typed(analyze(Path(step["stdout"]).read_text(), directory, case, admitted, contract), result["analysis"])):
                raise ValueError("whole A4 raw numerical evidence changed")
        if not same_typed(observed["runs"][0]["analysis"], observed["runs"][1]["analysis"]):
            raise ValueError("whole A4 repetition differs")
        if case["id"] in contract["instrumented_cases"]:
            step = steps[case["id"] + "_ubsan"]
            directory = run / "ubsan" / case["id"]
            if (step["exit_code"] or step["timed_out"] or Path(step["stderr"]).read_text() or
                    not same_typed(analyze(Path(step["stdout"]).read_text(), directory, case, admitted, contract),
                                   observed["runs"][0]["analysis"])):
                raise ValueError("whole A4 instrumented raw evidence changed")
    if not same_typed(analyze_matrix(report["cases"]), report["analysis"]):
        raise ValueError("whole A4 matrix analysis changed")
    destination.mkdir(parents=True, exist_ok=True)
    archive = destination / "raw_a4_graph_execution.tar.gz"
    results, verification = destination / "a4_results.json", destination / "a4_verification.json"
    if any(path.exists() for path in (archive, results, verification)):
        raise ValueError("whole A4 delivery refuses to overwrite existing evidence")
    files = []
    for directory, prefix in [(run, "a4_graph_execution"), *[(path, f"attempts/{path.name}") for path in attempts]]:
        if not directory.is_dir() or directory.is_symlink():
            raise ValueError("missing or symlinked whole A4 evidence directory")
        for path in sorted(directory.rglob("*")):
            relative = path.relative_to(directory)
            if (not path.is_file() or path.is_symlink() or any(name in relative.parts for name in ("CMakeFiles", "negative")) or
                    not (path.name in ("report.json", "contract.json", "analysis.json", "baseline.json", "inputs.json",
                         "build_report.json", "CMakeCache.txt", "compile_commands.json", "LastTest.log", "ubsan_dependencies.d") or
                         path.name.endswith((".stdout.txt", ".stderr.txt", ".resources.json")))):
                continue
            files.append((path, f"{prefix}/{relative.as_posix()}"))
    index = [{"path": name, "bytes": path.stat().st_size, "sha256": sha256_file(path)} for path, name in files]
    if len({item["path"] for item in index}) != len(index):
        raise ValueError("duplicate whole A4 archive members")
    with tarfile.open(archive, "w:gz") as tar:
        for path, name in files:
            tar.add(path, arcname=name, recursive=False)
    if any(sha256_file(path) != item["sha256"] for (path, _), item in zip(files, index, strict=True)):
        raise ValueError("whole A4 evidence changed while packaging")
    shutil.copyfile(run / "report.json", results)
    record = {"schema_version": 1, "status": STATUS, "archive_bytes": archive.stat().st_size,
        "archive_sha256": sha256_file(archive), "results_sha256": sha256_file(results), "files": index,
        "all_raw_numerical_inputs_binary_and_resource_evidence_rechecked": True,
        "indexed_not_archived": ["graph_inputs_and_full_state_u32le_captures", "original_HLS_instantiation_RTL"],
        "excluded": ["compiled_binaries", "author_source_trees", "regenerable_damaged_input_copies"]}
    atomic_write_json(verification, record)
    return record
