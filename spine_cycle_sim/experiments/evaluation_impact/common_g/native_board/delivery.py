"""Portable host-only evidence with raw native and old-matrix equivalence replay."""

import argparse
import json
from pathlib import Path
import re
import tarfile

from spine_cycle_sim.experiments.campaign_runtime import atomic_write_json, sha256_file
from spine_cycle_sim.experiments.original_regraph_execution.sssp_real_round.delivery import seal
from ..complete_pipeline.delivery import CHECKPOINT, verify as verify_archive
from ..continuous_board import analysis as old_analysis
from ..search_pipeline.synthesis import unchanged
from ..study import ROOT
from . import analysis, preparation

KIND = "native_five_shard_g_host_preflight_not_board"


def recheck(report, read):
    if report["status"] not in (analysis.PASS, "FAILED_RETAINED") or any(
            report.get(key) is not False for key in analysis.CLAIMS) or \
            bool(report["errors"]) != (report["status"] == "FAILED_RETAINED"):
        raise ValueError("invalid native host-only terminal claim")
    contract = json.loads(read("native_board_contract.json"))
    if contract != report["contract"] or contract["cases"] != [preparation.CASE]:
        raise ValueError("native preflight contract changed")
    steps = report["steps"]
    labels = ["compile-regression", "compile-native", *(case["case"] for case in contract["regression_cases"]),
              preparation.CASE["case"]]
    if [step["label"] for step in steps] != labels[:len(steps)]:
        raise ValueError("native execution order changed")
    for step in steps:
        label = step["label"]
        if {key: value for key, value in step.items() if key != "label"} != json.loads(read("raw/" + label + ".resources.json")):
            raise ValueError("native resource record changed")
        read("raw/" + label + ".stdout.txt")
        read("raw/" + label + ".stderr.txt")
    if report["status"] == "FAILED_RETAINED":
        return
    if len(steps) != len(labels) or any(step["exit_code"] or step["stop_reason"] != "process_exit" or
            step["cleanup_snapshot_error"] or step["tree_memory_gib"] != 4 or step["reserve_gib"] != 32 for step in steps):
        raise ValueError("native passing preflight lacks complete bounded execution")
    if set(report["binary_sha256"]) != {"probe", "regression-probe"} or any(
            not isinstance(digest, str) or not re.fullmatch(r"[0-9a-f]{64}", digest)
            for digest in report["binary_sha256"].values()):
        raise ValueError("native passing preflight lacks both compiled binary identities")
    if any(read("raw/" + label + "." + stream + ".txt").strip()
           for label in labels[:2] for stream in ("stdout", "stderr")):
        raise ValueError("native passing compilation has diagnostics")
    reference = json.loads(read("reference/results.json"))
    regressions = []
    for case in contract["regression_cases"]:
        label = case["case"]
        actual = old_analysis.analyze(case, read("raw/" + label + ".stdout.txt"), read("raw/" + label + ".stderr.txt"))
        prior_case = next(row for row in reference["contract"]["cases"] if row["case"] == label)
        prior = old_analysis.analyze(prior_case, read("reference/" + label + ".stdout.txt"), read("reference/" + label + ".stderr.txt"))
        saved_prior = next(row for row in reference["cases"] if row["case"] == label)
        if prior != {key: saved_prior[key] for key in ("setup", "rows")} or \
                analysis.deterministic(prior) != analysis.deterministic(actual):
            raise ValueError("old resident-state raw regression changed")
        regressions.append({"case": label, "equivalent": True, **actual})
    if len(regressions) != 6 or regressions != report["regression"]:
        raise ValueError("incomplete or changed old six-case regression")
    label = preparation.CASE["case"]
    native = analysis.analyze(preparation.CASE, read("raw/" + label + ".stdout.txt"), read("raw/" + label + ".stderr.txt"))
    if [{"case": label, **native}] != report["cases"]:
        raise ValueError("native raw result changed")
    if report["admission"].get("admitted") is not True or report["admission"].get("policy") != \
            "full_finite_budgets_plus_reserve_atomic_lease" or report["policy"] != {
                "tree_memory_gib": 4, "reserve_gib": 32, "allow_bounded_builds": True}:
        raise ValueError("native host preflight lacks atomic full-budget admission")
    events = dict(line.split() for line in report["memory_events_after"].splitlines())
    if any(events.get(key) != "0" for key in ("oom", "oom_kill", "oom_group_kill")):
        raise ValueError("native host preflight has an OOM event")


def validate(attempt, report):
    recheck(report, lambda name: (attempt / name).read_text())
    unchanged(report["pins"])
    if report["status"] == analysis.PASS and any(sha256_file(attempt / name) != digest
            for name, digest in report["binary_sha256"].items()):
        raise ValueError("native host binary changed")


def package(output, attempt):
    report = json.loads((attempt / "results.json").read_text())
    validate(attempt, report)
    files = {path.relative_to(attempt).as_posix(): path for path in sorted(attempt.rglob("*"))
             if path.is_file() and path.name not in ("probe", "regression-probe")}
    pin_members = {}
    for pin in report["pins"]:
        path = Path(pin["path"])
        if path.is_relative_to(attempt):
            member = path.relative_to(attempt).as_posix()
        elif path.is_relative_to(ROOT) and path.suffix == ".py":
            member = "runner_snapshot/" + path.relative_to(ROOT).as_posix()
            files[member] = path
        else:
            continue
        pin_members[pin["path"]] = member
    if any(path.is_symlink() for path in files.values()):
        raise ValueError("native host evidence cannot contain symlinks")
    output.mkdir(parents=True, exist_ok=False)
    archive = output / (attempt.name + ".tar.gz")
    members = seal([(path, member) for member, path in sorted(files.items())], archive)
    entry = {"attempt": attempt.name, "source": str(attempt), "archive": archive.name,
             "sha256": sha256_file(archive), "bytes": archive.stat().st_size, "files": members,
             "runner_root": str(ROOT), "pin_members": pin_members,
             **{key: report[key] for key in ("status", "errors", "cases", "regression")}}
    atomic_write_json(output / "index.json", {"status": CHECKPOINT, "study_kind": KIND,
        "attempts": [entry], "indexed_not_archived": ["executed_binaries", "external_compiler_and_system_dependencies"],
        **dict.fromkeys(analysis.CLAIMS, False)})
    return verify(output)


def verify(output):
    index = verify_archive(output)
    if index.get("study_kind") != KIND or any(index.get(key) is not False for key in analysis.CLAIMS):
        raise ValueError("invalid native host package claim")
    for entry in index["attempts"]:
        with tarfile.open(output / entry["archive"]) as bundle:
            def read(name):
                if not bundle.getmember(name).isfile():
                    raise ValueError("regular archive member required")
                return bundle.extractfile(name).read().decode("utf-8")
            report = json.loads(read("results.json"))
            recheck(report, read)
        if any(entry[key] != report[key] for key in ("status", "errors", "cases", "regression")):
            raise ValueError("native host archive and index disagree")
        members = {item["path"]: item["sha256"] for item in entry["files"]}
        for pin in report["pins"]:
            path = Path(pin["path"])
            if path.is_relative_to(Path(entry["source"])) or \
                    path.is_relative_to(Path(entry["runner_root"])) and path.suffix == ".py":
                if members.get(entry["pin_members"].get(pin["path"])) != pin["sha256"]:
                    raise ValueError("native host archive is missing a source/runner pin")
    return index


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--attempt", type=Path, required=True)
    args = parser.parse_args()
    package(args.output.resolve(), args.attempt.resolve())
