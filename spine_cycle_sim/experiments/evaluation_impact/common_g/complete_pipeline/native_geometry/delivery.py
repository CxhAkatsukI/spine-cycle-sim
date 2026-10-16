"""Seal and replay native source checks without depending on live campaign paths."""

import argparse
import json
from pathlib import Path
import tarfile

from spine_cycle_sim.experiments.campaign_runtime import atomic_write_json, sha256_file
from spine_cycle_sim.experiments.original_regraph_execution.sssp_real_round.delivery import seal
from ...study import ROOT
from ..delivery import CHECKPOINT, verify as verify_archive
from . import analysis


def recheck(report, read):
    if (report["status"] not in (analysis.PASS, "FAILED_RETAINED") or
            any(report.get(key) is not False for key in analysis.CLAIMS) or
            bool(report["errors"]) != (report["status"] == "FAILED_RETAINED") or
            report["contract"] != analysis.CONTRACT or
            json.loads(read("native_contract.json")) != analysis.CONTRACT):
        raise ValueError("invalid native source-only claim or contract")
    if [step["label"] for step in report["steps"]] not in (["compile"], ["compile", "native"]):
        raise ValueError("invalid native execution order")
    for step in report["steps"]:
        raw = "raw/" + step["label"]
        if {key: value for key, value in step.items() if key != "label"} != json.loads(read(raw + ".resources.json")):
            raise ValueError("native resource record differs from report")
        read(raw + ".stdout.txt")
        read(raw + ".stderr.txt")
    if report["status"] == "FAILED_RETAINED":
        return
    if [step["label"] for step in report["steps"]] != ["compile", "native"] or any(
            step["exit_code"] or step["stop_reason"] != "process_exit" or step["cleanup_snapshot_error"] or
            step["tree_memory_gib"] != 4 or step["reserve_gib"] != 32 for step in report["steps"]):
        raise ValueError("passing native check lacks successful bounded steps")
    if any(read("raw/compile." + stream + ".txt").strip() for stream in ("stdout", "stderr")):
        raise ValueError("passing compilation has unexpected diagnostics")
    actual = analysis.analyze(read("raw/native.stdout.txt"), read("raw/native.stderr.txt"))
    if actual != {key: report[key] for key in ("setup", "rows")}:
        raise ValueError("native raw rows disagree with saved analysis")
    events = dict(line.split() for line in report["memory_events_after"].splitlines())
    if any(events.get(key) != "0" for key in ("oom", "oom_kill", "oom_group_kill")):
        raise ValueError("native check contains an OOM event")
    if report["policy"] != {"tree_memory_gib": 4, "reserve_gib": 32, "allow_bounded_builds": True}:
        raise ValueError("native check memory policy changed")
    if report["admission"].get("admitted") is not True or report["admission"].get("policy") != \
            "full_finite_budgets_plus_reserve_atomic_lease":
        raise ValueError("native check lacks atomic complete-budget admission")


def package(output, attempts):
    if not attempts or len({attempt.name for attempt in attempts}) != len(attempts):
        raise ValueError("distinct native attempts required")
    prepared = []
    for attempt in attempts:
        report = json.loads((attempt / "results.json").read_text())
        recheck(report, lambda name: (attempt / name).read_text())
        if report["status"] == analysis.PASS and sha256_file(attempt / "probe") != report["binary_sha256"]:
            raise ValueError("native executed binary changed")
        files = {path.relative_to(attempt).as_posix(): path for path in sorted(attempt.rglob("*"))
                 if path.is_file() and path.name != "probe"}
        pin_members = {}
        for pin in report["pins"]:
            path = Path(pin["path"])
            if sha256_file(path) != pin["sha256"]:
                raise ValueError("native source/toolchain dependency changed")
            if path.is_relative_to(attempt):
                member = path.relative_to(attempt).as_posix()
            elif path.is_relative_to(ROOT) and path.suffix == ".py":
                member = "runner_snapshot/" + path.relative_to(ROOT).as_posix()
                files[member] = path
            else:
                continue
            pin_members[pin["path"]] = member
        if any(path.is_symlink() for path in files.values()):
            raise ValueError("native evidence contains a symlink")
        prepared.append((attempt, report, files, pin_members))
    output.mkdir(parents=True, exist_ok=False)
    entries = []
    for attempt, report, files, pin_members in prepared:
        archive = output / (attempt.name + ".tar.gz")
        members = seal([(path, name) for name, path in sorted(files.items())], archive)
        entries.append({"attempt": attempt.name, "source": str(attempt), "archive": archive.name,
                        "sha256": sha256_file(archive), "bytes": archive.stat().st_size, "files": members,
                        "pin_members": pin_members, "runner_root": str(ROOT),
                        **{key: report[key] for key in ("status", "errors", "rows")}})
    atomic_write_json(output / "index.json", {"status": CHECKPOINT, "study_kind": "native_geometry_complete_g",
        "attempts": entries, "indexed_not_archived": ["compiled_binary", "external_compiler_and_system_dependencies"],
        **dict.fromkeys(analysis.CLAIMS, False)})
    return verify(output)


def verify(output):
    index = verify_archive(output)
    if index.get("study_kind") != "native_geometry_complete_g":
        raise ValueError("wrong native source study")
    for entry in index["attempts"]:
        with tarfile.open(output / entry["archive"]) as bundle:
            def read(name):
                if not bundle.getmember(name).isfile():
                    raise ValueError("regular native archive member required")
                return bundle.extractfile(name).read().decode("utf-8")

            report = json.loads(read("results.json"))
            recheck(report, read)
        if any(entry[key] != report[key] for key in ("status", "errors", "rows")):
            raise ValueError("native archive and index disagree")
        members = {item["path"]: item["sha256"] for item in entry["files"]}
        if len(members) != len(entry["files"]):
            raise ValueError("duplicate native archive members")
        for pin in report["pins"]:
            path = Path(pin["path"])
            if path.is_relative_to(Path(entry["source"])) or \
                    path.is_relative_to(Path(entry["runner_root"])) and path.suffix == ".py":
                name = entry["pin_members"].get(pin["path"])
                if members.get(name) != pin["sha256"]:
                    raise ValueError("native archive is missing a frozen source or runner pin")
    return index


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--attempt", type=Path, action="append", required=True)
    args = parser.parse_args()
    package(args.output.resolve(), [path.resolve() for path in args.attempt])
