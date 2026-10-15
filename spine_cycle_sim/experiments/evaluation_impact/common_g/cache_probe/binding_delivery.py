"""Freeze production-wrapper evidence without claiming complete-G admission."""

import argparse
import hashlib
import json
from pathlib import Path, PurePosixPath
import tarfile

from spine_cycle_sim.experiments.campaign_runtime import atomic_write_json, sha256_file
from ..search_pipeline.synthesis import unchanged
from .binding_analysis import analyze, status

CLAIMS = ("hardware_timing_admitted", "production_baseline_admitted",
          "publication_match_admitted", "integrated_g_admitted")
CHECKPOINT = "CACHE_BINDING_COMPONENT_CHECKPOINT_NOT_HARDWARE_ADMISSION"
TERMINAL = ("CACHE_WRAPPER_RTL_ABI_PASS_TARGET_MET_REQUIRES_INTEGRATION",
            "CACHE_WRAPPER_RTL_ABI_PASS_CLOCK_GATE_FAILED", "FAILED_RETAINED")


def validate(attempt, report):
    if report["status"] not in TERMINAL or any(
            report.get(key) is not False for key in CLAIMS[:3]):
        raise ValueError("terminal unpromoted cache-wrapper evidence required")
    if bool(report["errors"]) != (report["status"] == "FAILED_RETAINED"):
        raise ValueError("cache-wrapper errors disagree with status")
    pins = report["source"] + [report["script"]]
    for pin in pins:
        Path(pin["path"]).relative_to(attempt)
    unchanged(pins)
    if "execution" in report:
        execution = report["execution"]
        if execution != json.loads((attempt / "attempt/execution.resources.json").read_text()):
            raise ValueError("cache-wrapper resource record changed")
        for key in ("stdout", "stderr"):
            Path(execution[key]).relative_to(attempt)
    if "analysis" in report:
        unchanged(report["analysis"]["artifacts"])
        observation = analyze(attempt / "attempt", attempt / "reference")
        if observation != report["analysis"]:
            raise ValueError("cache-wrapper raw reports disagree with analysis")
        if any(observation.get(key) is not False for key in CLAIMS):
            raise ValueError("component observation promoted a hardware claim")
    if report["status"] != "FAILED_RETAINED":
        if report["execution"]["exit_code"] or report["execution"]["timed_out"] or \
                status(report["analysis"]) != report["status"]:
            raise ValueError("cache-wrapper pass requires completed matching execution")


def selected(attempt):
    paths = {path for path in attempt.iterdir() if path.is_file()}
    for folder in ("source", "runner", "reference"):
        paths.update(path for path in (attempt / folder).rglob("*") if path.is_file())
    build = attempt / "attempt"
    paths.update(path for path in build.iterdir() if path.is_file())
    for folder in ("syn/report", "csim/report", "sim/report"):
        paths.update(path for path in (build / "project/solution" / folder).rglob("*") if path.is_file())
    return sorted(paths)


def package(output, attempt):
    report = json.loads((attempt / "results.json").read_text())
    validate(attempt, report)
    paths = selected(attempt)
    if any(path.is_symlink() for path in paths):
        raise ValueError("cache-wrapper capsule cannot contain symlinks")
    output.mkdir(parents=True, exist_ok=False)
    archive = output / (attempt.name + ".tar.gz")
    entry = {"attempt": attempt.name, "source": str(attempt), "status": report["status"],
             "errors": report["errors"], "files": [], "analysis": report.get("analysis", {})}
    with tarfile.open(archive, "w:gz") as stream:
        for path in paths:
            name = path.relative_to(attempt).as_posix()
            stream.add(path, arcname=name, recursive=False)
            entry["files"].append({"path": name, "sha256": sha256_file(path), "bytes": path.stat().st_size})
    entry.update(archive=archive.name, sha256=sha256_file(archive), bytes=archive.stat().st_size)
    index = {"status": CHECKPOINT, "attempts": [entry], **dict.fromkeys(CLAIMS, False),
             "integrated_rtl_admitted": False, "external_RTL_backpressure_tested": False}
    atomic_write_json(output / "index.json", index)
    verify(output)
    return index


def verify(output):
    index = json.loads((output / "index.json").read_text())
    if index["status"] != CHECKPOINT or any(index.get(key) is not False for key in (
            *CLAIMS, "integrated_rtl_admitted", "external_RTL_backpressure_tested")):
        raise ValueError("invalid cache-wrapper checkpoint claim boundary")
    for entry in index["attempts"]:
        if entry["status"] not in TERMINAL:
            raise ValueError("invalid cache-wrapper terminal status")
        archive = output / entry["archive"]
        if archive.parent != output or sha256_file(archive) != entry["sha256"]:
            raise ValueError("cache-wrapper archive identity changed")
        with tarfile.open(archive) as stream:
            if sorted(stream.getnames()) != sorted(row["path"] for row in entry["files"]):
                raise ValueError("cache-wrapper archive scope changed")
            for row in entry["files"]:
                name = PurePosixPath(row["path"])
                info = stream.getmember(row["path"])
                if name.is_absolute() or ".." in name.parts or not info.isfile() or info.size != row["bytes"]:
                    raise ValueError("invalid cache-wrapper archive member")
                if hashlib.sha256(stream.extractfile(info).read()).hexdigest() != row["sha256"]:
                    raise ValueError("cache-wrapper archived evidence changed")
            report = json.load(stream.extractfile("results.json"))
        if report["status"] != entry["status"] or report["errors"] != entry["errors"] or \
                report.get("analysis", {}) != entry["analysis"] or any(
                    report.get(key) is not False for key in CLAIMS[:3]):
            raise ValueError("cache-wrapper index contradicts archived report")
    return index


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--attempt", type=Path, required=True)
    args = parser.parse_args()
    package(args.output.resolve(), args.attempt.resolve())
