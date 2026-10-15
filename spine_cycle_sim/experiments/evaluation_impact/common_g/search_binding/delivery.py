"""Package the complete search binding source check without promoting timing."""

import argparse
import hashlib
import json
from pathlib import Path
import tarfile

from spine_cycle_sim.experiments.campaign_runtime import atomic_write_json, sha256_file
from .analysis import analyze

CLAIMS = ("hardware_timing_admitted", "production_baseline_admitted", "publication_match_admitted")


def package(output: Path, attempt: Path):
    report_path = attempt / "results.json"
    report = json.loads(report_path.read_text())
    if report["status"] != "SEARCH_BINDING_SOURCE_PASS_NOT_RTL" or report["errors"] or any(
            report.get(key) is not False for key in CLAIMS):
        raise ValueError("complete unpromoted source check required")
    for pin in report["source"] + report["dependencies"]:
        if sha256_file(Path(pin["path"])) != pin["sha256"]:
            raise ValueError("frozen source or compiler dependency changed")
    for label in ("compile", "execute"):
        record = report[label]
        if record["exit_code"] or record["timed_out"] or record != json.loads(
                (attempt / (label + ".resources.json")).read_text()):
            raise ValueError("unsuccessful or modified resource record")
        for key in ("stdout", "stderr"):
            Path(record[key]).relative_to(attempt)
    analysis = analyze(Path(report["execute"]["stdout"]).read_text())
    if analysis != report["analysis"] or sha256_file(attempt / "probe") != report["binary_sha256"]:
        raise ValueError("source output analysis or executed binary changed")
    paths = sorted([report_path, *[path for path in (attempt / "source").rglob("*") if path.is_file()],
                    *[path for path in attempt.iterdir() if path.is_file()
                      and path.name.endswith((".stdout.txt", ".stderr.txt", ".resources.json", ".d"))]])
    if any(path.is_symlink() for path in paths) or len(set(paths)) != len(paths):
        raise ValueError("invalid capsule membership")
    output.mkdir(parents=True, exist_ok=False)
    archive = output / "source_controls.tar.gz"
    members = []
    with tarfile.open(archive, "w:gz") as handle:
        for path in paths:
            name = path.relative_to(attempt).as_posix()
            handle.add(path, arcname=name, recursive=False)
            members.append({"path": name, "sha256": sha256_file(path), "bytes": path.stat().st_size})
    index = {"status": report["status"], "source_attempt": str(attempt), "calls": analysis["calls"],
             "claim": analysis["claim"], "archive": archive.name, "sha256": sha256_file(archive),
             "members": members, **dict.fromkeys(CLAIMS, False)}
    atomic_write_json(output / "index.json", index)
    verify(output)
    return index


def verify(output: Path):
    index = json.loads((output / "index.json").read_text())
    if index["status"] != "SEARCH_BINDING_SOURCE_PASS_NOT_RTL" or index["calls"] != 216 or any(
            index.get(key) is not False for key in CLAIMS):
        raise ValueError("invalid source-control claim")
    archive = output / index["archive"]
    if archive.parent != output or sha256_file(archive) != index["sha256"]:
        raise ValueError("capsule identity changed")
    with tarfile.open(archive) as handle:
        if sorted(handle.getnames()) != sorted(row["path"] for row in index["members"]):
            raise ValueError("capsule membership changed")
        for row in index["members"]:
            info = handle.getmember(row["path"])
            if not info.isfile() or info.size != row["bytes"] or hashlib.sha256(
                    handle.extractfile(info).read()).hexdigest() != row["sha256"]:
                raise ValueError("capsule member changed")
        report = json.load(handle.extractfile("results.json"))
        if report["status"] != index["status"] or report["errors"] or any(
                report.get(key) is not False for key in CLAIMS):
            raise ValueError("capsule report contradicts index")
        summary = analyze(handle.extractfile("execute.stdout.txt").read().decode())
        if summary != report["analysis"]:
            raise ValueError("capsule analysis differs from raw source output")
    return index


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--attempt", type=Path, required=True)
    args = parser.parse_args()
    package(args.output.resolve(), args.attempt.resolve())
