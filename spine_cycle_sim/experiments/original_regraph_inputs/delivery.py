"""Recheck complete input evidence and package logs with indexed large captures."""

from __future__ import annotations

import json
from pathlib import Path
import shutil
import tarfile

from spine_cycle_sim.experiments.campaign_runtime import atomic_write_json, sha256_file
from spine_cycle_sim.experiments.original_regraph_validation.analysis import same_typed
from .analysis import STATUS, analyze_layout
from .study import source_identities


def deliver(root: Path, run: Path, destination: Path, attempts: list[Path]) -> dict:
    report = json.loads((run / "report.json").read_text())
    contract = json.loads((run / "contract.json").read_text())
    if not same_typed(contract, json.loads((root / "configs/experiments/original_regraph_inputs_v1.json").read_text())):
        raise ValueError("input delivery requires the reviewed canonical contract")
    if (report["status"] != STATUS or report.get("ubsan_identical_no_diagnostics") is not True or
            source_identities(root) != report["source_identities"] or
            sha256_file(run / "contract.json") != report["contract_sha256"]):
        raise ValueError("incomplete or changed original-host input checkpoint")
    expected = [f"{topology['id']}_{item['id']}" for topology in contract["topologies"] for item in contract["inputs"]]
    if [case["id"] for case in report["cases"]] != expected:
        raise ValueError("input-delivery matrix differs from declared cases")
    if ([item["id"] for item in report["topologies"]] != [item["id"] for item in contract["topologies"]] or
            [item["id"] for item in report["inputs"]] != [item["id"] for item in contract["inputs"]]):
        raise ValueError("input delivery is missing or reorders a topology or graph")
    for observed, declared in zip(report["topologies"], contract["topologies"], strict=True):
        if not same_typed({key: observed.get(key) for key in declared}, declared):
            raise ValueError("input delivery topology differs from the contract")
    for observed, declared in zip(report["inputs"], contract["inputs"], strict=True):
        keys = ("vertices", "logical_edges", "sha256") if "sha256" in declared else ("vertices", "logical_edges")
        if not same_typed({key: observed.get(key) for key in keys}, {key: declared[key] for key in keys}):
            raise ValueError("input delivery graph differs from the contract")
    steps = {step["id"]: step for step in report["steps"]}
    if len(steps) != len(report["steps"]):
        raise ValueError("input delivery has duplicate execution steps")
    if [item["topology_id"] for item in report.get("instrumented_binaries", [])] != [
            item["id"] for item in contract["topologies"]]:
        raise ValueError("instrumented original-host matrix missing")
    for item in report["instrumented_binaries"]:
        if sha256_file(Path(item["path"])) != item["sha256"]:
            raise ValueError("instrumented original-host binary changed")
        for dependency in item["dependencies"]:
            if sha256_file(Path(dependency["path"])) != dependency["sha256"]:
                raise ValueError("instrumented original-host dependency changed")
    for topology in report["topologies"]:
        binary = run / topology["id"] / "probe"
        if sha256_file(binary) != topology["binary_sha256"]:
            raise ValueError("original-host binary changed before delivery")
        for item in topology["dependencies"]:
            if sha256_file(Path(item["path"])) != item["sha256"]:
                raise ValueError("original-host dependency changed before delivery")
        for graph in report["inputs"]:
            if sha256_file(Path(graph["path"])) != graph["sha256"]:
                raise ValueError("graph input changed before delivery")
            case = next(case for case in report["cases"] if case["id"] == f"{topology['id']}_{graph['id']}")
            if (case["status"] != STATUS or case.get("repeat_all_captures_identical") is not True or len(case["runs"]) != 2):
                raise ValueError("input case has incomplete repetition")
            for repetition, observed in zip(("first", "repeat"), case["runs"], strict=True):
                capture = Path(observed["directory"])
                step = steps[case["id"] + "_" + repetition]
                if (step["exit_code"] != 0 or step["timed_out"] or
                        sha256_file(capture / "layout.json") != observed["layout_sha256"] or
                        not same_typed(analyze_layout(Path(step["stdout"]).read_text(), capture, topology, graph, contract),
                                       observed["analysis"])):
                    raise ValueError("original-host raw input evidence changed before delivery")
            capture = run / topology["id"] / "ubsan" / graph["id"]
            step = steps[case["id"] + "_ubsan"]
            if (step["exit_code"] != 0 or step["timed_out"] or Path(step["stderr"]).read_text() or
                    not same_typed(analyze_layout(Path(step["stdout"]).read_text(), capture, topology, graph, contract),
                                   case["runs"][0]["analysis"])):
                raise ValueError("instrumented layout raw evidence changed before delivery")
    destination.mkdir(parents=True, exist_ok=True)
    archive = destination / "raw_original_host_inputs.tar.gz"
    results, verification = destination / "input_results.json", destination / "input_verification.json"
    if any(path.exists() for path in (archive, results, verification)):
        raise ValueError("input delivery refuses to overwrite evidence")
    files = []
    for directory, prefix in [(run, "host_input_study"), *[(path, f"attempts/{path.name}") for path in attempts]]:
        if not directory.is_dir() or directory.is_symlink():
            raise ValueError("missing or symlinked input evidence directory")
        for path in sorted(directory.rglob("*")):
            relative = path.relative_to(directory)
            if (not path.is_file() or path.is_symlink() or "prepared" in relative.parts or
                    not (path.name in ("report.json", "contract.json", "layout.json", "dependencies.d") or
                         path.name.endswith((".stdout.txt", ".stderr.txt", ".resources.json")))):
                continue
            files.append((path, f"{prefix}/{relative.as_posix()}"))
    index = [{"path": name, "bytes": path.stat().st_size, "sha256": sha256_file(path)} for path, name in files]
    with tarfile.open(archive, "w:gz") as tar:
        for path, name in files:
            tar.add(path, arcname=name, recursive=False)
    if any(sha256_file(path) != item["sha256"] for (path, _), item in zip(files, index, strict=True)):
        raise ValueError("input evidence changed during packaging")
    shutil.copyfile(run / "report.json", results)
    verification_record = {
        "schema_version": 1, "status": STATUS, "archive_bytes": archive.stat().st_size,
        "archive_sha256": sha256_file(archive), "results_sha256": sha256_file(results), "files": index,
        "all_source_dependencies_inputs_and_captures_rechecked": True,
        "indexed_not_archived": ["u32le_graph_and_layout_captures_regenerate_with_source_and_fixture_pins"],
        "excluded": ["author_source_trees", "compiled_binaries"],
    }
    atomic_write_json(verification, verification_record)
    return verification_record
