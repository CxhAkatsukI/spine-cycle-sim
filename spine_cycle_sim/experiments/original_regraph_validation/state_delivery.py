"""Recheck and package state evidence beside, never over, earlier checkpoints."""

from __future__ import annotations

import json
from pathlib import Path
import shutil
import tarfile

from spine_cycle_sim.experiments.campaign_runtime import atomic_write_json, sha256_file
from .analysis import admit_captures, same_typed
from .delivery import evidence_files
from .frontend_analysis import admit_protocol
from .state_analysis import STATUS, analyze_state
from .state_sources import admit_apply
from .study import source_identities


def deliver_state(root: Path, captures: Path, protocol: Path, apply_captures: Path,
                  run: Path, destination: Path, attempts: list[Path]) -> dict:
    report = json.loads((run / "report.json").read_text())
    contract = json.loads((run / "contract.json").read_text())
    if (report["status"] != STATUS or report.get("ubsan_identical_no_diagnostics") is not True or
            not report.get("negative_controls") or
            not all(row["expected_rejection"] for row in report["negative_controls"]) or
            source_identities(root) != report["source_identities"]):
        raise ValueError("state delivery requires a complete unchanged model/test checkpoint")
    if admit_apply(apply_captures, root, contract) != report["source_captures"]:
        raise ValueError("original Apply evidence changed before delivery")
    child_path = run / "frontend_regression/report.json"
    child = json.loads(child_path.read_text())
    child_contract = json.loads((child_path.parent / "contract.json").read_text())
    if (sha256_file(child_path) != report["frontend_regression"]["sha256"] or
            report["frontend_regression"]["analysis_identical"] is not True or
            admit_captures(captures, root, child_contract) != child["source_captures"] or
            admit_protocol(protocol, root, child_contract) != child["original_protocol"]):
        raise ValueError("frontend/source regression evidence changed before delivery")
    steps = {row["id"]: row for row in report["steps"]}
    text = lambda name: Path(steps[name]["stdout"]).read_text()
    analysis = analyze_state(text("state"), text("comparison"), text("iterations"),
        {name: text(name + "_repeat") for name in ("state", "comparison", "iterations")}, contract)
    if not same_typed(analysis, report["analysis"]):
        raise ValueError("state raw numerical evidence changed before delivery")
    if any(sha256_file(Path(row["path"])) != row["sha256"] for row in report["binaries"]):
        raise ValueError("tested state binary changed before delivery")
    destination.mkdir(parents=True, exist_ok=True)
    archive = destination / "raw_little_state_model.tar.gz"
    results, verification = destination / "state_results.json", destination / "state_verification.json"
    if any(path.exists() for path in (archive, results, verification)):
        raise ValueError("state delivery refuses to overwrite existing evidence")
    files = evidence_files(apply_captures, run)
    for directory, prefix in [(captures, "gather_source_captures"), (protocol, "original_scatter_protocol"),
                              *[(path, f"earlier_attempts/{path.name}") for path in attempts]]:
        if not directory.is_dir() or directory.is_symlink():
            raise ValueError("missing or symlinked source/earlier-attempt directory")
        files.extend((path, name.replace("source_captures/", f"{prefix}/", 1))
                     for path, name in evidence_files(directory, run) if name.startswith("source_captures/"))
    for relative in ("report.json", "contract.json", "build/CMakeCache.txt", "build/compile_commands.json",
                     "build/Testing/Temporary/LastTest.log"):
        files.append((child_path.parent / relative, f"frontend_regression_metadata/{relative}"))
    index = [{"path": name, "bytes": path.stat().st_size, "sha256": sha256_file(path)} for path, name in files]
    if len({row["path"] for row in index}) != len(index):
        raise ValueError("duplicate state archive names")
    with tarfile.open(archive, "w:gz") as tar:
        for path, name in files:
            tar.add(path, arcname=name, recursive=False)
    if any(sha256_file(path) != item["sha256"] for (path, _), item in zip(files, index, strict=True)):
        raise ValueError("state evidence changed during packaging")
    shutil.copyfile(run / "report.json", results)
    record = {
        "schema_version": 1, "status": STATUS, "evidence_class": report["evidence_class"],
        "archive_bytes": archive.stat().st_size, "archive_sha256": sha256_file(archive),
        "results_sha256": sha256_file(results), "files": index,
        "source_and_raw_results_rechecked": True, "earlier_attempts": [str(path) for path in attempts],
        "excluded": ["compiled_binaries", "author_source_trees", "regenerable_negative_fixtures"],
    }
    atomic_write_json(verification, record)
    return record
