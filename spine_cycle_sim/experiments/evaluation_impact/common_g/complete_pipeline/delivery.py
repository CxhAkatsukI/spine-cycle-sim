"""Package immutable complete-G source evidence without promoting hardware claims."""

import argparse
import hashlib
import json
from pathlib import Path, PurePosixPath
import tarfile

from spine_cycle_sim.experiments.campaign_runtime import atomic_write_json, sha256_file
from .analysis import analyze, diagnostics

PASS = "COMPLETE_G_SOURCE_COMPOSITION_PASS_NOT_INTEGRATED_RTL"
CLAIMS = ("hardware_timing_admitted", "production_baseline_admitted",
          "publication_match_admitted", "integrated_rtl_admitted")
CHECKPOINT = "COMPLETE_G_SOURCE_CHECKPOINT_NOT_HARDWARE_ADMISSION"


def validate(attempt: Path, report: dict):
    if report["status"] not in (PASS, "FAILED_RETAINED") or \
            any(report.get(key) is not False for key in CLAIMS):
        raise ValueError("invalid completed source-only claim boundary")
    if bool(report["errors"]) != (report["status"] == "FAILED_RETAINED"):
        raise ValueError("status disagrees with retained failures")
    pins = report["source"]
    if not pins or len({pin["path"] for pin in pins}) != len(pins):
        raise ValueError("missing or duplicate frozen source")
    for pin in pins:
        path = Path(pin["path"])
        path.relative_to(attempt / "source")
        if sha256_file(path) != pin["sha256"]:
            raise ValueError("frozen source changed")
    for label in ("compile", "execute"):
        if label not in report:
            continue
        stage = report[label]
        if stage != json.loads((attempt / f"{label}.resources.json").read_text()):
            raise ValueError("recorded resource log changed")
        for name in ("stdout", "stderr"):
            Path(stage[name]).relative_to(attempt)
    if report["status"] != PASS:
        return
    if any(report[label]["exit_code"] or report[label]["timed_out"]
           for label in ("compile", "execute")):
        raise ValueError("passing source check did not execute successfully")
    stdout = Path(report["execute"]["stdout"]).read_text()
    stderr = Path(report["execute"]["stderr"]).read_text()
    if analyze(stdout, stderr) != report["rows"] or diagnostics(stderr) != report["diagnostics"]:
        raise ValueError("raw source results disagree with analysis")
    if sha256_file(attempt / "probe") != report["binary_sha256"]:
        raise ValueError("executed binary changed")
    for pin in report["dependencies"]:
        if sha256_file(Path(pin["path"])) != pin["sha256"]:
            raise ValueError("compiled dependency changed")


def package(output: Path, attempts: list[Path]):
    if not attempts or len({path.name for path in attempts}) != len(attempts):
        raise ValueError("distinct named attempts required")
    reports = [json.loads((path / "results.json").read_text()) for path in attempts]
    for path, report in zip(attempts, reports, strict=True):
        validate(path, report)
    output.mkdir(parents=True, exist_ok=False)
    entries = []
    for attempt, report in zip(attempts, reports, strict=True):
        archive = output / (attempt.name + ".tar.gz")
        paths = sorted(path for path in attempt.rglob("*") if path.is_file() and
                       (path.is_relative_to(attempt / "source") or
                        path.parent == attempt and path.name != "probe"))
        if any(path.is_symlink() for path in paths):
            raise ValueError("evidence cannot contain symlinks")
        entry = {"attempt": attempt.name, "source": str(attempt), "status": report["status"],
                 "errors": report["errors"], "files": [], "rows": report.get("rows", []),
                 "diagnostics": report.get("diagnostics", {})}
        with tarfile.open(archive, "w:gz") as stream:
            for path in paths:
                name = path.relative_to(attempt).as_posix()
                stream.add(path, arcname=name, recursive=False)
                entry["files"].append({"path": name, "sha256": sha256_file(path),
                                       "bytes": path.stat().st_size})
        entry.update(archive=archive.name, sha256=sha256_file(archive), bytes=archive.stat().st_size)
        entries.append(entry)
    index = {"status": CHECKPOINT, "attempts": entries, **dict.fromkeys(CLAIMS, False)}
    atomic_write_json(output / "index.json", index)
    verify(output)
    return index


def verify(output: Path):
    index = json.loads((output / "index.json").read_text())
    if index["status"] != CHECKPOINT or any(index.get(key) is not False for key in CLAIMS):
        raise ValueError("invalid checkpoint claim boundary")
    for entry in index["attempts"]:
        archive = output / entry["archive"]
        if archive.parent != output or sha256_file(archive) != entry["sha256"]:
            raise ValueError("archive identity changed")
        with tarfile.open(archive) as stream:
            if sorted(stream.getnames()) != sorted(row["path"] for row in entry["files"]):
                raise ValueError("archive scope changed")
            for row in entry["files"]:
                name = PurePosixPath(row["path"])
                info = stream.getmember(row["path"])
                if name.is_absolute() or ".." in name.parts or not info.isfile() or \
                        info.size != row["bytes"]:
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
