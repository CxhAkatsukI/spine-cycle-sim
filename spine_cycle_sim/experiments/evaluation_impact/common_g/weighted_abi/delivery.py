"""Freeze weighted source controls, retaining failed attempts and claim limits."""

import argparse
import hashlib
import json
from pathlib import Path
import tarfile

from spine_cycle_sim.experiments.campaign_runtime import atomic_write_json, sha256_file
from .analysis import analyze, diagnostics, expected_cases
from .preparation import ADAPTERS

CLAIMS = ("hardware_timing_admitted", "production_baseline_admitted",
          "publication_match_admitted")
PASS = "WEIGHTED_SOURCE_ABI_PASS_NOT_TIMING"


def validate(attempt: Path, report: dict):
    search_mode = report.get("search_mode", "pristine")
    expected_cases(search_mode)
    if report["status"] not in (PASS, "FAILED_RETAINED"):
        raise ValueError("only completed weighted source attempts can be frozen")
    if any(report.get(key) is not False for key in CLAIMS):
        raise ValueError("source controls cannot promote a timing or baseline claim")
    if report["declared_adapters"] != list(ADAPTERS) or \
            [entry["adapter"] for entry in report["adapters"]] != list(ADAPTERS):
        raise ValueError("incomplete declared adapter scope")
    pins = [Path(pin["path"]) for pin in report["source"]]
    if not pins or len(set(pins)) != len(pins):
        raise ValueError("missing or duplicate frozen sources")
    for path, pin in zip(pins, report["source"], strict=True):
        path.relative_to(attempt / "source")
        if sha256_file(path) != pin["sha256"]:
            raise ValueError("frozen source changed")
    if report["status"] == PASS and (report["errors"] or
                                    any("error" in entry for entry in report["adapters"])):
        raise ValueError("passing attempt contains failures")
    if report["status"] == "FAILED_RETAINED" and not report["errors"]:
        raise ValueError("failed attempt must retain its failure reason")
    for entry in report["adapters"]:
        folder = attempt / entry["adapter"]
        for label in ("compile", "execute"):
            if label not in entry:
                continue
            stage = entry[label]
            resources = json.loads((folder / f"{label}.resources.json").read_text())
            if stage != resources:
                raise ValueError("recorded resource log changed")
            for key in ("stdout", "stderr"):
                Path(stage[key]).relative_to(folder)
        if report["status"] != PASS:
            continue
        for label in ("compile", "execute"):
            if entry[label]["exit_code"] or entry[label]["timed_out"]:
                raise ValueError("passing source control did not execute successfully")
        stdout = Path(entry["execute"]["stdout"]).read_text()
        stderr = Path(entry["execute"]["stderr"]).read_text()
        if analyze(stdout, stderr, search_mode=search_mode) != entry["rows"] or \
                diagnostics(stderr, search_mode=search_mode) != entry["diagnostics"]:
            raise ValueError("raw source results no longer agree with analysis")
        if sha256_file(folder / "probe") != entry["binary_sha256"]:
            raise ValueError("executed binary changed")
        for dependency in entry["dependencies"]:
            if sha256_file(Path(dependency["path"])) != dependency["sha256"]:
                raise ValueError("compiled dependency changed")


def selected_files(attempt: Path, report: dict):
    paths = {attempt / "results.json"}
    paths.update(path for path in (attempt / "source").rglob("*") if path.is_file())
    for entry in report["adapters"]:
        # Binary identity is recorded, but generated executables are not a source handoff.
        paths.update(path for path in (attempt / entry["adapter"]).iterdir()
                     if path.is_file() and path.name != "probe")
    if any(path.is_symlink() for path in paths):
        raise ValueError("evidence must not contain symlinks")
    return sorted(paths)


def package(output: Path, attempts: list[Path]):
    if not attempts or len({path.name for path in attempts}) != len(attempts):
        raise ValueError("distinct named attempts required")
    reports = [json.loads((path / "results.json").read_text()) for path in attempts]
    for attempt, report in zip(attempts, reports, strict=True):
        validate(attempt, report)
    output.mkdir(parents=True, exist_ok=False)
    entries = []
    for attempt, report in zip(attempts, reports, strict=True):
        archive = output / (attempt.name + ".tar.gz")
        entry = {"attempt": attempt.name, "source": str(attempt), "status": report["status"],
                 "search_mode": report.get("search_mode", "pristine"),
                 "errors": report["errors"], "files": [],
                 "adapters": [{key: value for key, value in arm.items()
                               if key in ("adapter", "error", "rows", "diagnostics")}
                              for arm in report["adapters"]]}
        with tarfile.open(archive, "w:gz") as stream:
            for path in selected_files(attempt, report):
                name = path.relative_to(attempt).as_posix()
                stream.add(path, arcname=name, recursive=False)
                entry["files"].append({"path": name, "sha256": sha256_file(path),
                                       "bytes": path.stat().st_size})
        entry.update(archive=archive.name, sha256=sha256_file(archive), bytes=archive.stat().st_size)
        entries.append(entry)
    index = {"status": "WEIGHTED_SOURCE_ABI_CHECKPOINT_NOT_G_ADMISSION", "attempts": entries,
             **dict.fromkeys(CLAIMS, False), "new_spine_comparison_executed": False}
    atomic_write_json(output / "index.json", index)
    verify(output)
    return index


def verify(output: Path):
    index = json.loads((output / "index.json").read_text())
    if index["status"] != "WEIGHTED_SOURCE_ABI_CHECKPOINT_NOT_G_ADMISSION" or \
            any(index.get(key) is not False for key in (*CLAIMS, "new_spine_comparison_executed")):
        raise ValueError("invalid checkpoint claim boundary")
    for entry in index["attempts"]:
        archive = output / entry["archive"]
        if archive.parent != output or sha256_file(archive) != entry["sha256"]:
            raise ValueError("archive identity changed")
        with tarfile.open(archive) as stream:
            if sorted(stream.getnames()) != sorted(row["path"] for row in entry["files"]):
                raise ValueError("archive scope changed")
            for row in entry["files"]:
                info = stream.getmember(row["path"])
                if not info.isfile() or info.size != row["bytes"]:
                    raise ValueError("invalid archived evidence member")
                member = stream.extractfile(info)
                if member is None or hashlib.sha256(member.read()).hexdigest() != row["sha256"]:
                    raise ValueError("archived evidence changed")
    return index


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--attempt", type=Path, action="append", required=True)
    args = parser.parse_args()
    package(args.output.resolve(), [path.resolve() for path in args.attempt])
