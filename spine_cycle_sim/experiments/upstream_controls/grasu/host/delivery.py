"""Recheck all guarded-host captures and preserved controls before immutable delivery."""

import hashlib
import json
from pathlib import Path
import shutil
import tarfile

from spine_cycle_sim.experiments.campaign_runtime import atomic_write_json, sha256_file
from ..analysis import analyze as legacy_analyze
from ..preparation import author_snapshot, preserve
from .analysis import STATUS, analyze
from .fixtures import NAMES
from .preparation import identities, validate
from .validation import INVALID, capture_negatives


def recheck(root: Path, run: Path, source: Path):
    report = json.loads((run / "report.json").read_text()); contract = json.loads((run / "contract.json").read_text()); validate(contract)
    canonical = root / "configs/experiments/original_grasu_host_v1.json"
    if (report["status"] != STATUS or report["source_identities"] != identities(root) or
            report["contract_sha256"] != sha256_file(canonical) or contract != json.loads(canonical.read_text()) or
            report["author_source"] != author_snapshot(root, source) or report["device_cycles"] is not None or
            report["publication_error_pct"] is not None): raise ValueError("G host checkpoint incomplete or changed")
    if preserve(root, Path(report["baseline"])) != report["preservation"]: raise ValueError("G host preservation changed")
    for item in report["inputs"]:
        if sha256_file(Path(item["path"])) != item["sha256"]: raise ValueError("G host input changed")
    for variant in report["variants"]:
        for item in variant["files"]:
            if sha256_file(Path(item["path"])) != item["sha256"]: raise ValueError("G host prepared source changed")
        for item in variant["patches"]:
            if sha256_file(root / item["path"]) != item["sha256"]: raise ValueError("G host patch changed")
    for binary in report["binaries"] + [report["legacy"]["binary"]]:
        for item in [binary, *binary["dependencies"]]:
            if sha256_file(Path(item["path"])) != item["sha256"]: raise ValueError("G host binary/dependency changed")
    steps = {step["id"]: step for step in report["steps"]}
    legacy_path = root / "docs/experiments/comparisons/grasu_regraph_stage_validation/grasu_source_path_results.json"
    previous = json.loads(legacy_path.read_text())
    required = [name + "_compile" for name in ("original", "row_guard", "both_guards", "ubsan")]
    required += ["bounds_original", "bounds_row_guard"]
    required += [name + "_" + suffix for name in NAMES for suffix in ("first", "repeat", "ubsan")]
    required += ["negative_" + name for name, _, _ in INVALID]
    required += ["legacy_compile"] + ["legacy_" + row["id"] for row in previous["cases"]] + ["focused_tests"]
    if list(steps) != required or len(steps) != len(report["steps"]): raise ValueError("G host fixed steps missing/reordered")
    for name, step in steps.items():
        expected = -6 if name.startswith("bounds_") else 1 if name.startswith("negative_") else 0
        if step["timed_out"] or step["exit_code"] != expected: raise ValueError("G host step status changed")
        resources = Path(step["stdout"]).with_name(name + ".resources.json")
        if json.loads(resources.read_text()) != {key: value for key, value in step.items() if key != "id"}: raise ValueError("G host resource record changed")
    for variant in ("original", "row_guard"):
        step = steps["bounds_" + variant]; diagnostic = Path(step["stderr"]).read_bytes()
        record = next(row for row in report["original_bounds_failures"] if row["id"] == variant)
        if (b"Assertion '__n < this->size()' failed." not in diagnostic or b"long unsigned int" not in diagnostic or
                hashlib.sha256(diagnostic).hexdigest() != record["stderr_sha256"]): raise ValueError("G host bounds rejection changed")
    for name, text, diagnostic in INVALID:
        if diagnostic not in Path(steps["negative_" + name]["stderr"]).read_text(): raise ValueError("G host malformed-input rejection changed")
        if (run / ("negative_" + name) / "input.txt").read_text() != text: raise ValueError("G host malformed input changed")
    if [row["id"] for row in report["cases"]] != list(NAMES): raise ValueError("G host fixed cases changed")
    indexed = []
    for row in report["cases"]:
        if row["status"] != STATUS or len(row["runs"]) != 3: raise ValueError("G host repeated/instrumented cases incomplete")
        for suffix, observed in zip(("first", "repeat", "ubsan"), row["runs"], strict=True):
            step = steps[row["id"] + "_" + suffix]; directory = Path(observed["directory"])
            value = analyze(run / "inputs" / (row["id"] + ".txt"), directory, Path(step["stdout"]), Path(step["stderr"]))
            if value != observed["analysis"] or value != row["runs"][0]["analysis"]: raise ValueError("G host raw analysis changed")
            indexed += [{"path": str(directory / item["name"]), "bytes": item["bytes"], "sha256": item["sha256"]}
                for item in value["captures"] if item["name"] in ("prepared.u64le", "updated.u64le")]
    step = steps["mixed_reservation_first"]
    negatives = capture_negatives(run / "inputs/mixed_reservation.txt", run / "captures/mixed_reservation/first", Path(step["stdout"]), Path(step["stderr"]))
    if negatives != report["capture_negatives"]: raise ValueError("G host actual-capture rejection changed")
    if sha256_file(legacy_path) != report["legacy"]["previous_results_sha256"]: raise ValueError("G host old checkpoint changed")
    if len(report["legacy"]["cases"]) != len(previous["cases"]): raise ValueError("G host old cases missing")
    for case, (observed, old) in enumerate(zip(report["legacy"]["cases"], previous["cases"], strict=True)):
        step = steps["legacy_" + old["id"]]; value = legacy_analyze(Path(observed["directory"]), case, Path(step["stdout"]), Path(step["stderr"]))
        if observed["id"] != old["id"] or value != observed["analysis"] or value != old["runs"][0]["analysis"]: raise ValueError("G host old complete state/protocol changed")
        indexed.append({"path": str(Path(observed["directory"]) / "state.u32le"), "bytes": value["state_bytes"], "sha256": value["state_sha256"]})
    return report, indexed


def deliver(root: Path, run: Path, source: Path, destination: Path, attempts: tuple[Path, ...] = ()):
    report, indexed = recheck(root, run, source)
    if len(set(attempts)) != len(attempts) or run in attempts: raise ValueError("G host duplicate historical attempt")
    files = [(Path(report["baseline"]) / "baseline.json", "baseline/baseline.json")]; historical = []

    def collect(directory, prefix):
        for path in sorted(directory.rglob("*")):
            if path.is_file() and not path.is_symlink() and (path.suffix in (".txt", ".json", ".diff", ".h", ".hpp", ".cpp", ".d") or
                    path.name.endswith((".u32le", ".u64le")) and path.name not in ("state.u32le", "prepared.u64le", "updated.u64le")):
                files.append((path, prefix + "/" + path.relative_to(directory).as_posix()))

    collect(run, "host")
    for attempt in attempts:
        collect(attempt, "attempts/" + attempt.name)
        historical.append({"path": str(attempt), "accepted": False, "reason": "noncanonical preflight; raw diagnostics and prepared source retained"})
    index = [{"path": name, "bytes": path.stat().st_size, "sha256": sha256_file(path)} for path, name in files]
    if len({item["path"] for item in index}) != len(index): raise ValueError("G host duplicate archive members")
    destination.mkdir(parents=True, exist_ok=True)
    result, verification, archive = [destination / name for name in ("grasu_host_results.json", "grasu_host_verification.json", "raw_grasu_host.tar.gz")]
    if any(path.exists() for path in (result, verification, archive)): raise ValueError("refuse to overwrite G host delivery")
    with tarfile.open(archive, "w:gz") as bundle:
        for path, name in files: bundle.add(path, arcname=name, recursive=False)
    with tarfile.open(archive, "r:gz") as bundle:
        if bundle.getnames() != [item["path"] for item in index]: raise ValueError("G host archive membership changed")
        for item in index:
            with bundle.extractfile(item["path"]) as stream:
                if hashlib.sha256(stream.read()).hexdigest() != item["sha256"]: raise ValueError("G host archive member changed")
    if any(sha256_file(path) != item["sha256"] for (path, _), item in zip(files, index, strict=True)): raise ValueError("G host evidence changed during packaging")
    shutil.copyfile(run / "report.json", result)
    record = {"schema_version": 1, "status": STATUS, "files": index, "indexed_full_states": indexed,
        "archive_sha256": sha256_file(archive), "archive_bytes": archive.stat().st_size, "results_sha256": sha256_file(result),
        "historical_attempts_not_accepted": historical, "actual_capture_negative_gates": report["capture_negatives"],
        "all_raw_states_protocols_sources_and_archive_members_rechecked": True,
        "original_host_without_compatibility_validated": False, "device_timing_validated": False, "publication_performance_match": False}
    atomic_write_json(verification, record); return record
