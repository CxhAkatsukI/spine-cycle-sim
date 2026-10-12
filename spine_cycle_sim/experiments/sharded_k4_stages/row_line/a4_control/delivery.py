"""Seal portable inputs, sources, binaries, complete states and raw diagnostics."""

import argparse
import hashlib
import json
from pathlib import Path
import shutil
import tarfile
import tempfile

from spine_cycle_sim.experiments.campaign_runtime import atomic_write_json, sha256_file
from spine_cycle_sim.experiments.original_regraph_execution.sssp_real_round.delivery import seal
from spine_cycle_sim.experiments.original_regraph_validation.analysis import same_typed
from .contract import LIMITS
from .recheck import recheck


def watchdog(run, resource=None):
    resource = resource or run.with_name(run.name + "_watchdog.resources.json")
    record = json.loads(resource.read_text())
    manifest = json.loads((run / "manifest.json").read_text())
    expected = [manifest["python_executable"], "-m", __package__ + ".study", "--worker", "--output",
                manifest["output"], "--pre-extraction"]
    if (record["command"][:-1] != expected or record["cwd"] != manifest["root"]
            or record["exit_code"] != 0 or record["stop_reason"] != "process_exit"
            or record["cleanup_snapshot_error"] is not None
            or record["tree_memory_gib"] != LIMITS["outer_tree_gib"]
            or record["timeout_seconds"] != LIMITS["outer_timeout_seconds"]
            or record["reserve_gib"] != 16 or record["peak_tree_rss_kib"] > 8 * 1024**2
            or record["minimum_available_bytes"] < 16 * 1024**3):
        raise ValueError("aggregate watchdog contract failed")
    return record


def deliver(run, destination):
    if destination.exists():
        raise FileExistsError("fresh evidence destination required")
    report = recheck(run)
    guard = watchdog(run)
    names = ["manifest.json", "results.json", "pre_extraction.tar.gz"]
    names += [row["relative"] for row in report["build_files"]]
    files = [(run / name, "run/" + name) for name in names]
    for directory in ("sources", "bases", "inputs", "expected", "states", "raw"):
        for path in sorted((run / directory).rglob("*")):
            if path.is_symlink():
                raise ValueError("symlink in model evidence")
            if path.is_file():
                files.append((path, "run/" + str(path.relative_to(run))))
    for suffix in ("resources.json", "stdout.txt", "stderr.txt"):
        files.append((run.with_name(run.name + "_watchdog." + suffix), "watchdog/" + suffix))
    destination.mkdir(parents=True)
    archive = destination / "raw_A4_control.tar.gz"
    index = seal(files, archive)
    shutil.copyfile(run / "results.json", destination / "results.json")
    record = {"status": report["status"], "files": index, "archive_bytes": archive.stat().st_size,
              "archive_sha256": sha256_file(archive), "results_sha256": sha256_file(destination / "results.json"),
              "aggregate_watchdog": guard, "scope": report["admission"],
              "historical_report_hashes_pinned": True, "default_plugin_untouched": True,
              "claim": "portable_raw_recheck_of_model_control_not_FPGA_calibration"}
    atomic_write_json(destination / "verification.json", record)
    return record


def verify(destination):
    record = json.loads((destination / "verification.json").read_text())
    archive = destination / "raw_A4_control.tar.gz"
    if (sha256_file(archive) != record["archive_sha256"] or archive.stat().st_size != record["archive_bytes"]
            or sha256_file(destination / "results.json") != record["results_sha256"]):
        raise ValueError("sealed evidence differs")
    entries = record["files"]
    expected = {row["path"]: row for row in entries}
    if (len(expected) != len(entries) or sum(row["bytes"] for row in entries) > 512 * 1024**2
            or any(Path(name).is_absolute() or ".." in Path(name).parts for name in expected)):
        raise ValueError("unsafe or duplicate archive index")
    with tempfile.TemporaryDirectory() as temporary, tarfile.open(archive, "r:gz") as bundle:
        members = bundle.getmembers()
        if len(members) != len(entries) or {member.name for member in members} != expected.keys():
            raise ValueError("archive membership differs")
        root = Path(temporary)
        for member in members:
            item = expected[member.name]
            if not member.isfile() or member.size != item["bytes"]:
                raise ValueError("archive member type or size differs")
            with bundle.extractfile(member) as content:
                data = content.read()
            if hashlib.sha256(data).hexdigest() != item["sha256"]:
                raise ValueError("archive member hash differs")
            path = root / member.name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(data)
        report = recheck(root / "run")
        guard = watchdog(root / "run", root / "watchdog/resources.json")
    if (not same_typed(report, json.loads((destination / "results.json").read_text()))
            or not same_typed(guard, record["aggregate_watchdog"]) or record["scope"] != report["admission"]
            or record["status"] != report["status"]):
        raise ValueError("portable raw conclusion differs")
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run", type=Path)
    parser.add_argument("--destination", type=Path, required=True)
    parser.add_argument("--verify-only", action="store_true")
    args = parser.parse_args()
    if args.verify_only:
        report = verify(args.destination.resolve())
    elif args.run:
        deliver(args.run.resolve(), args.destination.resolve())
        report = verify(args.destination.resolve())
    else:
        parser.error("--run is required for delivery")
    print(json.dumps({"status": report["status"], "portable_raw_recheck": "PASS"}, sort_keys=True))


if __name__ == "__main__":
    main()
