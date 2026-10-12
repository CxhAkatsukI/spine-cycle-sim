"""Seal production cross-row evidence, including failed synthesis attempts."""

import argparse
import hashlib
import json
from pathlib import Path
import shutil
import tarfile
import tempfile

from spine_cycle_sim.experiments.campaign_runtime import atomic_write_json, sha256_file
from spine_cycle_sim.experiments.original_regraph_execution.sssp_real_round.delivery import seal
from ..delivery import raw_files
from .recheck import recheck


def files(run, prefix):
    selected = raw_files(run, prefix, production=True)
    # Keep helper scheduling estimates and synthesis failures, not huge tool databases.
    for path in sorted((run / "production/build").rglob("*")):
        if path.is_file() and (path.name == "vitis_hls.log" or
                "syn/report" in path.as_posix() and path.suffix in (".rpt", ".xml")):
            name = prefix + "/" + path.relative_to(run).as_posix()
            if name not in {entry for _, entry in selected}:
                selected.append((path, name))
    return selected


def deliver(run, destination, failed_attempts=()):
    if destination.exists():
        raise FileExistsError("fresh evidence destination required")
    report = recheck(run)
    selected = files(run, "run")
    for index, attempt in enumerate(failed_attempts):
        if json.loads((attempt / "failure.json").read_text())["status"] != "FAILED_RETAINED":
            raise ValueError("development attempt must be explicitly non-admitted")
        selected += files(attempt, f"development/{index}_{attempt.name}")
    destination.mkdir(parents=True)
    archive = destination / "raw_cross_row.tar.gz"
    entries = seal(selected, archive)
    shutil.copyfile(run / "results.json", destination / "results.json")
    record = {"status": report["status"], "files": entries,
              "archive_sha256": sha256_file(archive), "archive_bytes": archive.stat().st_size,
              "results_sha256": sha256_file(destination / "results.json"),
              "claim": "production_RTL_and_synthesis_not_routed_FPGA_or_simulator_calibration",
              "indexed_not_redistributed": ["proprietary_tools_and_compiled_simulation_images"]}
    atomic_write_json(destination / "verification.json", record)
    return record


def verify(destination):
    record = json.loads((destination / "verification.json").read_text())
    archive = destination / "raw_cross_row.tar.gz"
    if (sha256_file(archive) != record["archive_sha256"] or archive.stat().st_size != record["archive_bytes"]
            or sha256_file(destination / "results.json") != record["results_sha256"]):
        raise ValueError("sealed cross-row package differs")
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
    if report != json.loads((destination / "results.json").read_text()) or report["status"] != record["status"]:
        raise ValueError("portable raw conclusion differs")
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run", type=Path)
    parser.add_argument("--destination", type=Path, required=True)
    parser.add_argument("--failed-attempt", type=Path, action="append", default=[])
    parser.add_argument("--verify-only", action="store_true")
    args = parser.parse_args()
    if not args.verify_only:
        if args.run is None:
            parser.error("--run required for delivery")
        deliver(args.run.resolve(), args.destination.resolve(), [path.resolve() for path in args.failed_attempt])
    print(json.dumps({"status": verify(args.destination.resolve())["status"], "portable_raw_recheck": "PASS"}))


if __name__ == "__main__":
    main()
