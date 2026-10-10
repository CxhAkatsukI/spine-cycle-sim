"""Revalidate the complete declared matrix and package indexed large captures."""

import hashlib
import json
from pathlib import Path
import shutil
import tarfile
import tempfile

from spine_cycle_sim.experiments.campaign_runtime import atomic_write_json, sha256_file
from ..upstream_controls.grasu.analysis import analyze as analyze_source
from .analysis import analyze, equivalent
from .preparation import build_identity, identities, prepare, preserve


def check_manifest(report, contract):
    expected = [(row["id"], repeat) for row in contract["matrix"] for repeat in range(contract["repetitions"])]
    if (report["status"] != "G_FINITE_SOURCE16_STATE_LEDGER_PASS_NOT_TIMING" or report["contract"] != contract or
            [(row["id"], row["repetition"]) for row in report["rows"]] != expected or
            [row["id"] for row in report["ubsan_rows"]] != contract["ubsan_rows"] or
            [row["case"] for row in report["source_rows"]] != list(range(8)) or
            report["source_rows"] != report["source_ubsan_rows"]):
        raise ValueError("finite G complete matrix, evidence kind or source/sanitizer gate differs")
    expected_steps = []
    for case in range(8):
        expected_steps.extend((f"source_{case}", f"source_ubsan_{case}"))
    for row in contract["matrix"]:
        expected_steps.extend(f'{row["id"]}_{repeat}' for repeat in range(contract["repetitions"]))
        if row["id"] in contract["ubsan_rows"]:
            expected_steps.append(row["id"] + "_ubsan")
    if [Path(step["stdout"]).name.removesuffix(".stdout.txt") for step in report["steps"]] != expected_steps:
        raise ValueError("finite G required execution sequence differs")


def recheck(root: Path, run: Path):
    report = json.loads((run / "report.json").read_text())
    contract = json.loads((root / "configs/experiments/original_grasu_finite_v1.json").read_text())
    check_manifest(report, contract)
    if report["model"]["files"] != identities(root) or report["preservation"] != preserve(root, Path(report["baseline"])):
        raise ValueError("finite G model or baseline preservation changed")
    if len(report["builds"]) != 2 or report["builds"] != [build_identity(Path(row["binary"])) for row in report["builds"]]:
        raise ValueError("finite G compiled binary/tool/flags changed")
    for binary in report["source_binaries"]:
        for field in [binary, *binary["dependencies"]]:
            if sha256_file(Path(field["path"])) != field["sha256"]:
                raise ValueError("original G binary or dependencies changed")
    for case, fields in report["inputs"].items():
        with tempfile.TemporaryDirectory() as scratch:
            regenerated = prepare(Path(scratch) / "input", int(case))
            if [(Path(row["path"]).name, row["sha256"]) for row in regenerated] != [(Path(row["path"]).name, row["sha256"]) for row in fields]:
                raise ValueError("finite G input regeneration differs")
        if any(sha256_file(Path(row["path"])) != row["sha256"] for row in fields):
            raise ValueError("finite G input changed")
    steps = {}
    for step in report["steps"]:
        name = Path(step["stdout"]).name.removesuffix(".stdout.txt")
        raw = run / "logs" / (name + ".resources.json")
        if json.loads(raw.read_text()) != step or step["exit_code"] or step["timed_out"]:
            raise ValueError("finite G raw resource record or successful execution changed")
        steps[name] = step
    for label, key in (("source", "source_rows"), ("source_ubsan", "source_ubsan_rows")):
        for case, row in enumerate(report[key]):
            step = steps[f"{label}_{case}"]
            equivalent(row, analyze_source(run / label / str(case), case, Path(step["stdout"]), Path(step["stderr"])))
    reference = {}
    definitions = {row["id"]: row for row in contract["matrix"]}
    for row in report["rows"] + report["ubsan_rows"]:
        name = row["id"]; case = definitions[name]["case"]
        suffix = str(row["repetition"]) if "repetition" in row else "ubsan"
        step = steps[name + "_" + suffix]
        capture = run / "finite" / name / suffix if "repetition" in row else run / "ubsan" / name
        current = analyze(capture, case, Path(step["stdout"]), Path(step["stderr"]))
        equivalent(row["result"], current)
        memory = {**contract["memory"], **definitions[name]}
        if (current["timing"] != contract["timing"] or
                any(current[key] != memory[field] for key, field in (("fifo_depth", "fifo_depth"),
                    ("memory_latency", "latency"), ("bank_credits", "bank_credits")))):
            raise ValueError("finite G compiled timing/resource settings changed")
        if name in reference:
            equivalent(reference[name], current)
        reference[name] = current
    equivalent(reference["lane_257"], reference["lane_257_reverse"])
    equivalent(reference["mixed_three_batches"], reference["mixed_reverse"])
    return report


def deliver(root: Path, run: Path, destination: Path, attempts=()):
    report = recheck(root, run)
    names = ("finite_grasu_results.json", "finite_grasu_verification.json", "raw_finite_grasu.tar.gz")
    if any((destination / name).exists() for name in names):
        raise ValueError("refuse to overwrite finite G delivery")
    destination.mkdir(parents=True, exist_ok=True)
    selected = [(Path(report["baseline"]) / "baseline.json", "baseline/baseline.json")]
    for directory, prefix in [(run, "formal"), *((path, "attempts/" + path.name) for path in attempts)]:
        for path in sorted(directory.rglob("*")):
            if path.is_file() and not path.is_symlink() and (path.suffix in (".json", ".txt", ".tsv") or path.name == "protocol.u32le"):
                selected.append((path, prefix + "/" + path.relative_to(directory).as_posix()))
    selected.extend((root / row["path"], "source/" + row["path"]) for row in report["model"]["files"])
    for index, build in enumerate(report["builds"]):
        for row in build["files"]:
            path = Path(row["path"])
            selected.append((path, f"build_{index}/" + path.relative_to(Path(build["binary"]).parent.parent).as_posix()))
    manifest = [{"path": name, "bytes": path.stat().st_size, "sha256": sha256_file(path)} for path, name in selected]
    if len({row["path"] for row in manifest}) != len(manifest):
        raise ValueError("duplicate finite G archive member")
    archive = destination / names[2]
    with tarfile.open(archive, "w:gz") as bundle:
        for path, name in selected:
            bundle.add(path, arcname=name, recursive=False)
    with tarfile.open(archive, "r:gz") as bundle:
        if bundle.getnames() != [row["path"] for row in manifest]:
            raise ValueError("finite G archive membership differs")
        for row in manifest:
            with bundle.extractfile(row["path"]) as stream:
                if hashlib.sha256(stream.read()).hexdigest() != row["sha256"]:
                    raise ValueError("finite G archive contents differ")
    if recheck(root, run) != report:
        raise ValueError("finite G evidence changed during packaging")
    shutil.copyfile(run / "report.json", destination / names[0])
    verification = {"status": report["status"], "all_raw_rows_rechecked": True,
        "results_sha256": sha256_file(destination / names[0]), "archive_sha256": sha256_file(archive),
        "archive_bytes": archive.stat().st_size, "files": manifest,
        "large_payloads": [{"path": str(path), "bytes": path.stat().st_size, "sha256": sha256_file(path)}
                           for path in sorted(run.rglob("*")) if path.is_file() and path.suffix in (".bin", ".u32le", ".u64le")],
        "historical_attempts_not_accepted": [str(path) for path in attempts],
        "publication_or_fpga_timing_match": False}
    atomic_write_json(destination / names[1], verification)
    return verification
