"""Package raw component evidence without binaries or author-source trees."""

from __future__ import annotations

import json
from pathlib import Path
import shutil
import tarfile

from spine_cycle_sim.experiments.campaign_runtime import atomic_write_json, sha256_file
from .analysis import admit_captures


def evidence_files(captures: Path, run: Path) -> list[tuple[Path, str]]:
    files = []
    for directory, prefix in ((captures, "source_captures"), (run, "finite_model")):
        for path in sorted(directory.rglob("*")):
            relative = path.relative_to(directory)
            if not path.is_file() or path.is_symlink():
                continue
            if any(part in ("prepared", "negative_fixtures", "CMakeFiles") for part in relative.parts):
                continue
            if (len(relative.parts) == 1 and path.name in (
                    "report.json", "contract.json", "source_pins.json")) or path.name.endswith((
                        ".stdout.txt", ".stderr.txt", ".resources.json", ".u32le", "dependencies.d")) or (
                        prefix == "finite_model" and relative.as_posix() in (
                            "build/CMakeCache.txt", "build/compile_commands.json",
                            "build/Testing/Temporary/LastTest.log")):
                files.append((path, f"{prefix}/{relative.as_posix()}"))
    return files


def deliver(root: Path, captures: Path, run: Path, destination: Path) -> dict:
    report = json.loads((run / "report.json").read_text())
    contract = json.loads((run / "contract.json").read_text())
    if (report["status"] != "FINITE_GATHER_MERGE_FUNCTIONAL_PASS_TIMING_PREDICTED" or
            not report.get("negative_controls") or
            not all(row["expected_rejection"] for row in report["negative_controls"])):
        raise ValueError("cannot deliver an incomplete finite-component checkpoint")
    if admit_captures(captures, root, contract) != report["source_captures"]:
        raise ValueError("source captures changed before delivery")
    for item in report["source_identities"]:
        if sha256_file(root / item["path"]) != item["sha256"]:
            raise ValueError("tested model/runner source changed before delivery")
    destination.mkdir(parents=True, exist_ok=True)
    archive = destination / "raw_little_finite_model.tar.gz"
    results = destination / "finite_gather_results.json"
    verification = destination / "finite_gather_verification.json"
    if any(path.exists() for path in (archive, results, verification)):
        raise ValueError("delivery refuses to overwrite an existing checkpoint")
    files = evidence_files(captures, run)
    index = [{"path": name, "bytes": path.stat().st_size, "sha256": sha256_file(path)}
             for path, name in files]
    with tarfile.open(archive, "w:gz") as tar:
        for path, name in files:
            tar.add(path, arcname=name, recursive=False)
    for (path, _name), identity in zip(files, index, strict=True):
        if sha256_file(path) != identity["sha256"]:
            raise ValueError("raw evidence changed while packaging")
    shutil.copyfile(run / "report.json", results)
    record = {
        "schema_version": 1, "evidence_class": report["evidence_class"],
        "status": report["status"], "archive_sha256": sha256_file(archive),
        "archive_bytes": archive.stat().st_size, "files": index,
        "results_sha256": sha256_file(results), "source_capture_hashes_checked": True,
        "model_and_runner_source_hashes_checked": True,
        "package_code_sha256": sha256_file(Path(__file__)),
        "excluded": ["compiled_binaries", "author_source_trees", "regenerable_negative_fixtures"],
    }
    atomic_write_json(verification, record)
    return record
