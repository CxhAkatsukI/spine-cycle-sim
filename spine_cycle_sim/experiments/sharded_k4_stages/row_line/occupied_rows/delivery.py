"""Seal a small self-contained RTL/source/log package and recheck after relocation."""

import argparse
import hashlib
import json
from pathlib import Path
import shutil
import tarfile
import tempfile

from spine_cycle_sim.experiments.campaign_runtime import atomic_write_json, sha256_file
from spine_cycle_sim.experiments.original_regraph_execution.sssp_real_round.delivery import seal
from .recheck import recheck


def raw_files(run, prefix):
    files = [(run / name, prefix + "/" + name) for name in ("manifest.json", "results.json", "failure.json")
             if (run / name).is_file()]
    for path in sorted((run / "sources").rglob("*")):
        if path.is_symlink():
            raise ValueError("symlink in source archive")
        if path.is_file():
            files.append((path, prefix + "/" + str(path.relative_to(run))))
    for arm in ("reference", "candidate"):
        for path in sorted((run / arm).iterdir()) if (run / arm).is_dir() else []:
            if path.is_file() and path.suffix in (".v", ".vh", ".sv", ".tcl", ".json", ".txt", ".log"):
                files.append((path, prefix + "/" + str(path.relative_to(run))))
    return files


def deliver(run, destination, failed_attempts=()):
    if destination.exists():
        raise FileExistsError("fresh delivery directory required")
    report = recheck(run)
    files = raw_files(run, "run")
    for index, attempt in enumerate(failed_attempts):
        if json.loads((attempt / "failure.json").read_text())["status"] != "FAILED_RETAINED":
            raise ValueError("failed attempt is not explicitly non-admitted")
        files.extend(raw_files(attempt, f"development/{index}_{attempt.name}"))
    destination.mkdir(parents=True)
    archive = destination / "raw_occupied_rows.tar.gz"
    index = seal(files, archive)
    shutil.copyfile(run / "results.json", destination / "results.json")
    record = {"status": report["status"], "files": index,
              "archive_sha256": sha256_file(archive), "archive_bytes": archive.stat().st_size,
              "results_sha256": sha256_file(destination / "results.json"),
              "indexed_not_redistributed": ["proprietary_Xilinx_tools_and_compiled_simulation_images"],
              "claim": "complete_RTL_handshake_replay_not_FPGA_timing"}
    atomic_write_json(destination / "verification.json", record)
    return record


def verify(destination):
    record = json.loads((destination / "verification.json").read_text())
    archive = destination / "raw_occupied_rows.tar.gz"
    if (sha256_file(archive) != record["archive_sha256"] or archive.stat().st_size != record["archive_bytes"]
            or sha256_file(destination / "results.json") != record["results_sha256"]):
        raise ValueError("sealed package identity differs")
    entries = {row["path"]: row for row in record["files"]}
    if (len(entries) != len(record["files"]) or sum(row["bytes"] for row in entries.values()) > 256 * 1024**2
            or any(Path(name).is_absolute() or ".." in Path(name).parts for name in entries)):
        raise ValueError("unsafe evidence index")
    with tempfile.TemporaryDirectory() as temporary, tarfile.open(archive, "r:gz") as bundle:
        members = bundle.getmembers()
        if len(members) != len(entries) or {member.name for member in members} != entries.keys():
            raise ValueError("archive membership differs")
        root = Path(temporary)
        for member in members:
            entry = entries[member.name]
            if not member.isfile() or member.size != entry["bytes"]:
                raise ValueError("archive member type or size differs")
            with bundle.extractfile(member) as stream:
                data = stream.read()
            if hashlib.sha256(data).hexdigest() != entry["sha256"]:
                raise ValueError("archive member identity differs")
            path = root / member.name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(data)
        report = recheck(root / "run")
    if report != json.loads((destination / "results.json").read_text()) or record["status"] != report["status"]:
        raise ValueError("portable raw conclusion differs")
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run", type=Path)
    parser.add_argument("--destination", type=Path, required=True)
    parser.add_argument("--verify-only", action="store_true")
    parser.add_argument("--failed-attempt", type=Path, action="append", default=[])
    args = parser.parse_args()
    if not args.verify_only:
        if args.run is None:
            parser.error("--run required for delivery")
        deliver(args.run.resolve(), args.destination.resolve(), [path.resolve() for path in args.failed_attempt])
    print(json.dumps({"status": verify(args.destination.resolve())["status"], "portable_raw_recheck": "PASS"}))


if __name__ == "__main__":
    main()
