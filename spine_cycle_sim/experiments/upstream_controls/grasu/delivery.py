"""Re-admit raw G controls before archiving; large full states remain hash-indexed."""

import hashlib
import json
from pathlib import Path
import shutil
import tarfile

from spine_cycle_sim.experiments.campaign_runtime import atomic_write_json, sha256_file
from .analysis import STATUS, analyze
from .fixtures import NAMES
from .preparation import author_snapshot, identities, legacy_reference, preserve
from .validation import negative_controls


def deliver(root: Path, run: Path, source: Path, destination: Path, attempts: tuple[Path, ...] = ()):
    report = json.loads((run / "report.json").read_text()); contract = json.loads((run / "contract.json").read_text())
    canonical = root / "configs/experiments/original_grasu_source_path_v1.json"
    if (report["status"] != STATUS or report["source_identities"] != identities(root) or
            report["contract_sha256"] != sha256_file(canonical) or contract != json.loads(canonical.read_text()) or
            report["author_source"] != author_snapshot(root, source) or report["device_cycles"] is not None or
            report["publication_error_pct"] is not None): raise ValueError("G source checkpoint incomplete or changed")
    if preserve(root, Path(report["baseline"])) != report["preservation"]: raise ValueError("G preservation changed")
    steps = {step["id"]: step for step in report["steps"]}
    required = [family + "_compile" for family in ("normal", "ubsan", "legacy")]
    required += [name + "_" + suffix for name in NAMES for suffix in ("first", "repeat", "ubsan")]
    required += ["legacy_cache", "focused_tests"]
    if list(steps) != required or len(steps) != len(report["steps"]): raise ValueError("G raw steps incomplete or reordered")
    if [row["id"] for row in report["cases"]] != list(NAMES): raise ValueError("G fixed matrix changed")
    indexed = []
    for step in steps.values():
        if step["exit_code"] or step["timed_out"]: raise ValueError("G raw step failed")
    for case, row in enumerate(report["cases"]):
        if row["status"] != STATUS or len(row["runs"]) != 3: raise ValueError("G repetition/instrumentation missing")
        for suffix, observed in zip(("first", "repeat", "ubsan"), row["runs"], strict=True):
            step = steps[row["id"] + "_" + suffix]; directory = Path(observed["directory"])
            result = analyze(directory, case, Path(step["stdout"]), Path(step["stderr"]))
            if result != observed["analysis"] or result != row["runs"][0]["analysis"]: raise ValueError("G raw state/protocol changed")
            indexed.append({"path": str(directory / "state.u32le"), "bytes": result["state_bytes"], "sha256": result["state_sha256"]})
    for stream in ("stdout", "stderr"):
        if Path(steps["legacy_cache"][stream]).read_bytes() != legacy_reference(root, stream): raise ValueError("G legacy output changed")
    step = steps["mixed_three_batches_first"]
    if negative_controls(run / "mixed_three_batches/first", Path(step["stdout"]), Path(step["stderr"])) != report["negative_controls"]:
        raise ValueError("G actual-capture negative gates changed")
    for binary in report["binaries"]:
        for item in [binary, *binary["dependencies"]]:
            if sha256_file(Path(item["path"])) != item["sha256"]: raise ValueError("G binary/dependency changed")
    files = [(Path(report["baseline"]) / "baseline.json", "baseline/baseline.json")]
    for path in sorted(run.rglob("*")):
        if path.is_file() and not path.is_symlink() and (path.suffix == ".txt" or path.name in (
                "report.json", "contract.json", "dependencies.d", "protocol.u32le") or path.name.endswith(".resources.json")):
            files.append((path, "grasu/" + path.relative_to(run).as_posix()))
    prior = []
    if len(set(attempts)) != len(attempts) or run in attempts: raise ValueError("duplicate G historical attempt")
    for attempt in attempts:
        previous = json.loads((attempt / "report.json").read_text())
        prior.append({"path": str(attempt), "status": previous["status"], "error": previous.get("error"),
            "report_sha256": sha256_file(attempt / "report.json"), "accepted": False})
        for path in sorted(attempt.rglob("*")):
            if path.is_file() and not path.is_symlink() and (path.name.endswith((".stdout.txt", ".stderr.txt", ".resources.json")) or
                    path.name in ("report.json", "contract.json", "dependencies.d")):
                files.append((path, "attempts/" + attempt.name + "/" + path.relative_to(attempt).as_posix()))
    index = [{"path": name, "bytes": path.stat().st_size, "sha256": sha256_file(path)} for path, name in files]
    destination.mkdir(parents=True, exist_ok=True)
    paths = [destination / name for name in ("grasu_source_path_results.json", "grasu_source_path_verification.json", "raw_grasu_source_path.tar.gz")]
    if any(path.exists() for path in paths): raise ValueError("refuse to overwrite G delivery")
    with tarfile.open(paths[2], "w:gz") as bundle:
        for path, name in files: bundle.add(path, arcname=name, recursive=False)
    with tarfile.open(paths[2], "r:gz") as bundle:
        if bundle.getnames() != [item["path"] for item in index]: raise ValueError("G archive membership changed")
        for item in index:
            with bundle.extractfile(item["path"]) as stream:
                if hashlib.sha256(stream.read()).hexdigest() != item["sha256"]: raise ValueError("G archive member changed")
    if any(sha256_file(path) != item["sha256"] for (path, _), item in zip(files, index, strict=True)):
        raise ValueError("G raw evidence changed during packaging")
    shutil.copyfile(run / "report.json", paths[0])
    record = {"schema_version": 1, "status": STATUS, "files": index, "indexed_full_states": indexed,
        "archive_sha256": sha256_file(paths[2]), "archive_bytes": paths[2].stat().st_size,
        "results_sha256": sha256_file(paths[0]), "historical_attempts_not_accepted": prior,
        "actual_capture_negative_gates": report["negative_controls"], "all_raw_states_protocols_sources_and_archive_members_rechecked": True,
        "device_timing_validated": False, "original_host_validated": False, "publication_performance_match": False}
    atomic_write_json(paths[1], record); return record
