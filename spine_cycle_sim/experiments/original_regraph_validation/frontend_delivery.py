"""Package the input-path checkpoint separately from frozen Gather evidence."""

from __future__ import annotations

import json
from pathlib import Path
import shutil
import tarfile

from spine_cycle_sim.experiments.campaign_runtime import atomic_write_json, sha256_file
from .analysis import admit_captures
from .delivery import evidence_files
from .frontend_analysis import admit_protocol, analyze_frontend


def deliver_frontend(root: Path, captures: Path, protocol: Path, run: Path,
                     destination: Path, attempts: list[Path]) -> dict:
    report = json.loads((run / "report.json").read_text())
    contract = json.loads((run / "contract.json").read_text())
    if (report["status"] != "FINITE_MEMORY_FRONTEND_FUNCTIONAL_PASS_TIMING_PREDICTED" or
            report.get("frozen_gather_and_captures_identical") is not True or
            report.get("ubsan_identical_no_diagnostics") is not True or
            not report.get("negative_controls") or
            not all(row["expected_rejection"] for row in report["negative_controls"])):
        raise ValueError("cannot package incomplete frontend validation")
    if (admit_captures(captures, root, contract) != report["source_captures"] or
            admit_protocol(protocol, root, contract) != report["original_protocol"]):
        raise ValueError("original source evidence changed before packaging")
    for item in report["source_identities"]:
        if sha256_file(root / item["path"]) != item["sha256"]:
            raise ValueError("tested source changed before packaging")
    steps = {row["id"]: row for row in report["steps"]}
    analysis = analyze_frontend(
        Path(steps["frontend"]["stdout"]).read_text(),
        Path(steps["frontend_repeat"]["stdout"]).read_text(), report["original_protocol"], contract)
    if analysis != report["analysis"]:
        raise ValueError("frontend raw output changed before packaging")
    destination.mkdir(parents=True, exist_ok=True)
    archive = destination / "raw_little_frontend_model.tar.gz"
    results = destination / "frontend_results.json"
    verification = destination / "frontend_verification.json"
    if any(path.exists() for path in (archive, results, verification)):
        raise ValueError("frontend delivery refuses to overwrite existing evidence")
    files = evidence_files(captures, run)
    for directory, prefix in [(protocol, "original_protocol"), *[
            (path, f"earlier_attempts/{path.name}") for path in attempts]]:
        if not directory.is_dir() or directory.is_symlink():
            raise ValueError("missing or symlinked earlier evidence directory")
        files.extend((path, name.replace("source_captures/", f"{prefix}/", 1))
                     for path, name in evidence_files(directory, run)
                     if name.startswith("source_captures/"))
    index = [{"path": name, "bytes": path.stat().st_size, "sha256": sha256_file(path)}
             for path, name in files]
    if len({row["path"] for row in index}) != len(index):
        raise ValueError("duplicate raw evidence archive names")
    with tarfile.open(archive, "w:gz") as tar:
        for path, name in files:
            tar.add(path, arcname=name, recursive=False)
    if any(sha256_file(path) != item["sha256"]
           for (path, _), item in zip(files, index, strict=True)):
        raise ValueError("raw evidence changed during packaging")
    shutil.copyfile(run / "report.json", results)
    record = {
        "schema_version": 1, "status": report["status"],
        "evidence_class": report["evidence_class"], "archive_bytes": archive.stat().st_size,
        "archive_sha256": sha256_file(archive), "results_sha256": sha256_file(results),
        "files": index, "source_and_raw_results_rechecked": True,
        "earlier_attempts": [str(path) for path in attempts],
        "excluded": ["compiled_binaries", "author_source_trees", "regenerable_negative_fixtures"],
    }
    atomic_write_json(verification, record)
    return record
