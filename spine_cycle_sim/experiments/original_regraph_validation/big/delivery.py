"""Freeze admitted component logs/captures without rewriting earlier evidence."""

import json
from pathlib import Path
import shutil
import tarfile

from spine_cycle_sim.experiments.campaign_runtime import atomic_write_json, sha256_file
from .analysis import STATUS, analyze_tests, analyze_comparison
from .study import source_identities


def deliver(root: Path, run: Path, destination: Path) -> dict:
    report = json.loads((run / "report.json").read_text())
    contract_path = root / "configs/experiments/original_regraph_big_gather_validation_v1.json"
    contract = json.loads(contract_path.read_text())
    if (report.get("status") != STATUS or report.get("ubsan_identical_no_diagnostics") is not True or
            report.get("FPGA_cycles") is not None or report.get("publication_error_pct") is not None or
            report.get("contract_sha256") != sha256_file(contract_path) or
            report.get("source_identities") != source_identities(root)):
        raise ValueError("cannot deliver incomplete or changed Big checkpoint")
    if (len(report["legacy"]["checks"]) != 12 or not all(row["identical"] is True for row in report["legacy"]["checks"]) or
            report["negative_controls"] != [{"id": kind, "rejected": True, "sha256": sha256_file(run / (kind + ".u32le"))}
                                            for kind in ("changed", "truncated", "excess")]):
        raise ValueError("Big legacy or negative gates incomplete")
    for step in report["steps"]:
        if step["timed_out"] or (step["exit_code"] != 0) != step["id"].startswith("negative_"):
            raise ValueError("Big raw execution failed its expected exit gate")
    for name, analyzer in (("big_tests", analyze_tests), ("big_comparison", analyze_comparison)):
        texts = []
        for suffix in ("first", "repeat"):
            step = next(step for step in report["steps"] if step["id"] == name + "_" + suffix)
            text = Path(step["stdout"]).read_text()
            if analyzer(text, contract) != report[name] or Path(step["stderr"]).read_text():
                raise ValueError("Big raw result changed")
            texts.append(text)
        if texts[0] != texts[1] or (run / ("ubsan_" + name + ".stdout.txt")).read_text() != texts[0]:
            raise ValueError("Big repeated/instrumented raw result changed")
    identities = report["source_control"]["dependencies"] + report["binaries"] + [
        report["source_control"]["binary"], report["source_control"]["capture"]]
    for identity in identities:
        if sha256_file(Path(identity["path"])) != identity["sha256"]:
            raise ValueError("Big raw compiled dependency/binary/capture changed")
    destination.mkdir(parents=True, exist_ok=True)
    targets = [destination / name for name in ("big_gather_results.json", "big_gather_verification.json", "raw_big_gather.tar.gz")]
    if any(path.exists() for path in targets): raise ValueError("refuse to overwrite Big delivery")
    files = []
    for path in sorted(run.rglob("*")):
        relative = path.relative_to(run)
        if not path.is_file() or path.is_symlink() or any(part in ("prepared", "CMakeFiles", "legacy_a4") for part in relative.parts):
            continue
        if path.name in ("changed.u32le", "truncated.u32le", "excess.u32le"): continue
        if path.name.endswith((".stdout.txt", ".stderr.txt", ".resources.json", ".u32le", "dependencies.d")) or (
                relative.as_posix() in ("report.json", "contract.json", "build/CMakeCache.txt",
                    "build/compile_commands.json", "build/Testing/Temporary/LastTest.log")):
            files.append((path, "big_components/" + relative.as_posix()))
    baseline = root / "results/upstream_stage_controls/big_gather_baseline_v1"
    for path in sorted(baseline.iterdir()):
        if path.is_file(): files.append((path, "legacy_baseline/" + path.name))
    previous = root / "results/upstream_stage_controls/a4_execution_final_v3"
    for name in ("report.json", "contract.json"):
        files.append((previous / name, "accepted_a4_reference/" + name))
    old = json.loads((previous / "report.json").read_text())
    for step in old["steps"]:
        if step["id"].endswith("_first"):
            for key in ("stdout", "stderr"):
                path = Path(step[key])
                files.append((path, "accepted_a4_reference/" + path.name))
    index = [{"path": name, "sha256": sha256_file(path), "bytes": path.stat().st_size} for path, name in files]
    if len({row["path"] for row in index}) != len(index): raise ValueError("Big archive members not unique")
    with tarfile.open(targets[2], "w:gz") as archive:
        for path, name in files: archive.add(path, arcname=name, recursive=False)
    if any(sha256_file(path) != row["sha256"] for (path, _), row in zip(files, index, strict=True)):
        raise ValueError("Big raw evidence changed during packaging")
    shutil.copyfile(run / "report.json", targets[0])
    verification = {"schema_version": 1, "status": STATUS, "files": index,
        "results_sha256": sha256_file(targets[0]), "archive_sha256": sha256_file(targets[2]),
        "archive_bytes": targets[2].stat().st_size, "raw_and_source_identities_rechecked": True,
        "excluded": ["compiled_binaries", "author_source_trees", "regenerable_negative_captures", "A4_state_replicas_indexed_in_results"]}
    atomic_write_json(targets[1], verification)
    return verification
