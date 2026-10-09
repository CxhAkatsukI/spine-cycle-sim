"""Package admitted Big source protocol and finite-memory evidence separately."""

import json
from pathlib import Path
import shutil
import tarfile

from spine_cycle_sim.experiments.campaign_runtime import atomic_write_json, sha256_file
from .frontend_analysis import STATUS, analyze
from .frontend_study import identities


def deliver(root: Path, run: Path, destination: Path) -> dict:
    report = json.loads((run / "report.json").read_text())
    contract_path = root / "configs/experiments/original_regraph_big_frontend_validation_v1.json"
    contract = json.loads(contract_path.read_text())
    if (report.get("status") != STATUS or report.get("ubsan_identical_no_diagnostics") is not True or
            report.get("source_control", {}).get("repeated_and_ubsan_identical") is not True or
            report.get("legacy_big_comparison_identical") is not True or report.get("source_identities") != identities(root) or
            report.get("contract_sha256") != sha256_file(contract_path) or
            report.get("FPGA_cycles") is not None or report.get("publication_error_pct") is not None):
        raise ValueError("Big frontend checkpoint incomplete or changed")
    if len(report["legacy"]["checks"]) != 13 or not all(row["identical"] is True for row in report["legacy"]["checks"]):
        raise ValueError("Big frontend legacy gates incomplete")
    for step in report["steps"]:
        if step["timed_out"] or (step["exit_code"] != 0) != step["id"].startswith("negative_"):
            raise ValueError("Big frontend raw execution no longer passes")
    for name in ("big_frontend_tests", "big_frontend_comparison"):
        texts = []
        for suffix in ("first", "repeat"):
            step = next(row for row in report["steps"] if row["id"] == name + "_" + suffix)
            text = Path(step["stdout"]).read_text(); texts.append(text)
            if analyze(text, contract, name.endswith("comparison")) != report[name] or Path(step["stderr"]).read_text():
                raise ValueError("Big frontend raw model output changed")
        if texts[0] != texts[1] or (run / ("ubsan_" + name + ".stdout.txt")).read_text() != texts[0]:
            raise ValueError("Big frontend repeat/instrumentation changed")
    for item in report["source_control"]["dependencies"] + report["source_control"]["binaries"] + report["binaries"] + [report["source_control"]["capture"]]:
        if sha256_file(Path(item["path"])) != item["sha256"]: raise ValueError("Big frontend source/binary/capture changed")
    if [row["id"] for row in report["negative_controls"]] != ["header", "request", "response", "update", "truncated", "excess"] or (
            any(row["rejected"] is not True or row["sha256"] != sha256_file(run / ("negative_" + row["id"] + ".u32le"))
                for row in report["negative_controls"])): raise ValueError("Big frontend malformed-capture gates missing")
    files = []
    for path in sorted(run.rglob("*")):
        rel = path.relative_to(run)
        if (not path.is_file() or path.is_symlink() or any(part in ("prepared", "CMakeFiles", "legacy_a4") for part in rel.parts) or
                path.name.startswith("negative_") and path.suffix == ".u32le"): continue
        if path.name.endswith((".stdout.txt", ".stderr.txt", ".resources.json", ".u32le", "dependencies.d")) or rel.as_posix() in (
                "report.json", "contract.json", "build/CMakeCache.txt", "build/compile_commands.json", "build/Testing/Temporary/LastTest.log"):
            files.append((path, "big_frontend/" + rel.as_posix()))
    baseline = root / "results/upstream_stage_controls/big_frontend_baseline_v1"
    files += [(path, "legacy_baseline/" + path.name) for path in sorted(baseline.iterdir()) if path.is_file()]
    old = root / "docs/experiments/comparisons/grasu_regraph_stage_validation/big_gather_results.json"
    files.append((old, "accepted_big_gather/results.json"))
    capture = Path(json.loads(old.read_text())["source_control"]["capture"]["path"])
    files.append((capture, "accepted_big_gather/source_capture.u32le"))
    index = [{"path": name, "sha256": sha256_file(path), "bytes": path.stat().st_size} for path, name in files]
    if len({row["path"] for row in index}) != len(index): raise ValueError("duplicate Big frontend archive members")
    destination.mkdir(parents=True, exist_ok=True)
    results, verification, archive = [destination / name for name in (
        "big_frontend_results.json", "big_frontend_verification.json", "raw_big_frontend.tar.gz")]
    if any(path.exists() for path in (results, verification, archive)): raise ValueError("refuse to overwrite Big frontend delivery")
    with tarfile.open(archive, "w:gz") as bundle:
        for path, name in files: bundle.add(path, arcname=name, recursive=False)
    if any(sha256_file(path) != row["sha256"] for (path, _), row in zip(files, index, strict=True)):
        raise ValueError("Big frontend raw evidence changed while packaging")
    shutil.copyfile(run / "report.json", results)
    record = {"schema_version": 1, "status": STATUS, "files": index, "archive_sha256": sha256_file(archive),
        "archive_bytes": archive.stat().st_size, "results_sha256": sha256_file(results),
        "raw_and_tested_source_hashes_rechecked": True,
        "excluded": ["compiled_binaries", "author_source_trees", "regenerable_negative_captures", "A4_state_payloads_indexed_in_results"]}
    atomic_write_json(verification, record)
    return record
