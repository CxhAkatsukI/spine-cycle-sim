"""Seal real-input source checks, preserving failed attempts and claim boundaries."""

import argparse
import json
from pathlib import Path
import tarfile

from spine_cycle_sim.experiments.campaign_runtime import atomic_write_json, sha256_file
from spine_cycle_sim.experiments.original_regraph_execution.sssp_real_round.delivery import seal
from ...search_pipeline.synthesis import unchanged
from ..delivery import CHECKPOINT, verify as verify_archive
from .analysis import CLAIMS, PASS, analyze


def terminal(report):
    if report["status"] not in (PASS, "FAILED_RETAINED") or any(
            report.get(key) is not False for key in CLAIMS):
        raise ValueError("invalid host-prepared source-only claim boundary")
    if bool(report["errors"]) != (report["status"] == "FAILED_RETAINED"):
        raise ValueError("status disagrees with retained failures")


def validate(attempt, report):
    terminal(report)
    pins = report["source"]
    if not pins or len({p["path"] for p in pins}) != len(pins):
        raise ValueError("missing or duplicate frozen source")
    for pin in pins:
        relative = Path(pin["path"]).relative_to(attempt)
        if relative.parts[0] != "source" and relative.as_posix() != "contract.json":
            raise ValueError("source pin outside frozen inputs")
    unchanged(pins)
    if report["contract"] != json.loads((attempt / "contract.json").read_text()):
        raise ValueError("real-input contract changed")
    steps = report["steps"]
    if len({s["label"] for s in steps}) != len(steps):
        raise ValueError("duplicate execution step")
    for step in steps:
        record = {k: v for k, v in step.items() if k != "label"}
        if record != json.loads((attempt / (step["label"] + ".resources.json")).read_text()):
            raise ValueError("recorded resource log changed")
        for stream in ("stdout", "stderr"):
            if Path(step[stream]).parent != attempt:
                raise ValueError("raw stream outside attempt")
    if report["status"] != PASS:
        return
    cases = report["contract"]["cases"]
    if [s["label"] for s in steps] != ["compile", *(c["case"] for c in cases)] or any(
            s["exit_code"] or s["timed_out"] for s in steps):
        raise ValueError("passing campaign did not execute its complete matrix")
    if any(Path(steps[0][s]).read_text().strip() for s in ("stdout", "stderr")):
        raise ValueError("passing compilation has unexpected diagnostics")
    rows = []
    for case, step in zip(cases, steps[1:], strict=True):
        rows += analyze(case, Path(step["stdout"]).read_text(), Path(step["stderr"]).read_text())
    if rows != report["rows"] or sha256_file(attempt / "probe") != report["binary_sha256"]:
        raise ValueError("raw execution differs from passing analysis/binary")
    unchanged(report["dependencies"])


def package(output, attempts):
    if not attempts or len({p.name for p in attempts}) != len(attempts):
        raise ValueError("distinct named real-input attempts required")
    reports = [json.loads((p / "results.json").read_text()) for p in attempts]
    for attempt, report in zip(attempts, reports, strict=True):
        validate(attempt, report)
    output.mkdir(parents=True, exist_ok=False)
    entries = []
    for attempt, report in zip(attempts, reports, strict=True):
        paths = sorted(p for p in attempt.rglob("*") if p.is_file() and
                       (p.is_relative_to(attempt / "source") or p.parent == attempt and p.name != "probe"))
        if any(p.is_symlink() for p in paths):
            raise ValueError("evidence cannot contain symlinks")
        archive = output / (attempt.name + ".tar.gz")
        files = seal([(p, p.relative_to(attempt).as_posix()) for p in paths], archive)
        entries.append({"attempt": attempt.name, "source": str(attempt), "status": report["status"],
                        "errors": report["errors"], "rows": report["rows"], "files": files,
                        "archive": archive.name, "sha256": sha256_file(archive), "bytes": archive.stat().st_size})
    index = {"status": CHECKPOINT, "study_kind": "real_host_prepared_complete_g",
             "attempts": entries, **dict.fromkeys(CLAIMS, False)}
    atomic_write_json(output / "index.json", index)
    return verify(output)


def verify(output):
    index = verify_archive(output)
    if index.get("study_kind") != "real_host_prepared_complete_g":
        raise ValueError("wrong source study")
    for entry in index["attempts"]:
        with tarfile.open(output / entry["archive"]) as bundle:
            report = json.load(bundle.extractfile("results.json"))
        terminal(report)
        if any(entry[key] != report[key] for key in ("status", "errors", "rows")):
            raise ValueError("archive and real-input index disagree")
    return index


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--attempt", type=Path, action="append", required=True)
    args = parser.parse_args()
    package(args.output.resolve(), [p.resolve() for p in args.attempt])
