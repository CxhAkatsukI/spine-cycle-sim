"""Seal host preflight evidence; never admit it as a successful board test."""

import argparse
import json
from pathlib import Path
import tarfile

from spine_cycle_sim.experiments.campaign_runtime import atomic_write_json, sha256_file
from spine_cycle_sim.experiments.original_regraph_execution.sssp_real_round.delivery import seal
from ..complete_pipeline.delivery import CHECKPOINT, verify as verify_archive
from ..search_pipeline.synthesis import unchanged
from .analysis import CLAIMS, PASS, analyze

KIND = "continuous_g_host_preflight_not_board"


def terminal(report):
    if report["status"] not in (PASS, "FAILED_RETAINED") or any(
            report.get(key) is not False for key in CLAIMS):
        raise ValueError("invalid host-only claim boundary")
    if bool(report["errors"]) != (report["status"] == "FAILED_RETAINED"):
        raise ValueError("status disagrees with retained failures")


def validate(attempt, report):
    terminal(report)
    pins = report["source"]
    if not pins or len({p["path"] for p in pins}) != len(pins):
        raise ValueError("missing or duplicate frozen source")
    for pin in pins:
        relative = Path(pin["path"]).relative_to(attempt)
        if relative.parts[0] != "source" and relative.as_posix() not in (
                "contract.json", "continuous_contract.json"):
            raise ValueError("source pin outside frozen inputs")
    unchanged(pins)
    contract = json.loads((attempt / "continuous_contract.json").read_text())
    if contract != report["contract"]:
        raise ValueError("continuous contract changed")
    cases = contract["cases"]
    names = {f"{dataset}-{suffix}" for dataset in ("AU", "SU", "WK")
             for suffix in ("mixed-512", "weight_change-4096")}
    if len(cases) != 6 or {row["case"] for row in cases} != names or any(
            row["partition_vertices"] != 65536 or len(row["batches"]) != 3 for row in cases):
        raise ValueError("wrong native host preflight matrix")
    steps = report["steps"]
    if len({row["label"] for row in steps}) != len(steps):
        raise ValueError("duplicate execution step")
    for step in steps:
        resource = json.loads((attempt / (step["label"] + ".resources.json")).read_text())
        if {key: value for key, value in step.items() if key != "label"} != resource:
            raise ValueError("recorded resource log changed")
        if any(Path(step[stream]).parent != attempt for stream in ("stdout", "stderr")):
            raise ValueError("raw stream outside attempt")
    if report["status"] != PASS:
        return
    if [row["label"] for row in steps] != ["compile", *(row["case"] for row in cases)] or any(
            row["exit_code"] or row["timed_out"] for row in steps):
        raise ValueError("passing preflight did not execute its complete matrix")
    if any(Path(steps[0][stream]).read_text().strip() for stream in ("stdout", "stderr")):
        raise ValueError("passing compilation has unexpected diagnostics")
    actual = [{"case": case["case"], **analyze(case, Path(step["stdout"]).read_text(),
                                               Path(step["stderr"]).read_text())}
              for case, step in zip(cases, steps[1:], strict=True)]
    if actual != report["cases"] or sha256_file(attempt / "probe") != report["binary_sha256"]:
        raise ValueError("raw execution differs from passing analysis/binary")
    unchanged(report["dependencies"])


def package(output, attempts):
    if not attempts or len({path.name for path in attempts}) != len(attempts):
        raise ValueError("distinct named attempts required")
    reports = [json.loads((path / "results.json").read_text()) for path in attempts]
    for path, report in zip(attempts, reports, strict=True):
        validate(path, report)
    output.mkdir(parents=True, exist_ok=False)
    entries = []
    for attempt, report in zip(attempts, reports, strict=True):
        paths = sorted(path for path in attempt.rglob("*") if path.is_file() and
                       (path.is_relative_to(attempt / "source") or path.parent == attempt and path.name != "probe"))
        if any(path.is_symlink() for path in paths):
            raise ValueError("evidence cannot contain symlinks")
        archive = output / (attempt.name + ".tar.gz")
        files = seal([(path, path.relative_to(attempt).as_posix()) for path in paths], archive)
        entries.append({"attempt": attempt.name, "source": str(attempt), "status": report["status"],
                        "errors": report["errors"], "cases": report["cases"], "files": files,
                        "archive": archive.name, "sha256": sha256_file(archive), "bytes": archive.stat().st_size})
    atomic_write_json(output / "index.json", {"status": CHECKPOINT, "study_kind": KIND,
                                              "attempts": entries, **dict.fromkeys(CLAIMS, False)})
    return verify(output)


def verify(output):
    index = verify_archive(output)
    if index.get("study_kind") != KIND or any(index.get(key) is not False for key in CLAIMS):
        raise ValueError("wrong host preflight or promoted claim boundary")
    for entry in index["attempts"]:
        with tarfile.open(output / entry["archive"]) as bundle:
            report = json.load(bundle.extractfile("results.json"))
        terminal(report)
        if any(entry[key] != report[key] for key in ("status", "errors", "cases")):
            raise ValueError("archive and host preflight index disagree")
    return index


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--attempt", type=Path, action="append", required=True)
    args = parser.parse_args()
    package(args.output.resolve(), [path.resolve() for path in args.attempt])
