"""Seal and independently recheck the whole-line simulator checkpoint."""

import argparse
import hashlib
import json
from pathlib import Path
import tarfile
import tempfile

from spine_cycle_sim.experiments.campaign_runtime import atomic_write_json, sha256_file
from spine_cycle_sim.experiments.original_regraph_execution.sssp_real_round.delivery import seal
from spine_cycle_sim.experiments.original_regraph_validation.analysis import same_typed
from .delivery import raw_files
from .model_recheck import read_json, recheck, recheck_study
from .model_scope import RESIDENT


def deliver_resident(run: Path, plugin: Path, destination: Path) -> dict:
    if destination.exists():
        raise FileExistsError("fresh resident delivery directory required")
    if read_json(run / "manifest.json").get("study_scope") != RESIDENT.name:
        raise ValueError("resident package requires the pinned real-graph scope")
    report = recheck_study(run, plugin)
    destination.mkdir(parents=True)
    archive = destination / "raw_model.tar.gz"
    files = raw_files(run, "sst") + [(plugin, "plugin/libspine_cycle.so")]
    index = seal(files, archive)
    atomic_write_json(destination / "results.json", report)
    record = {"schema_version": 1, "package_kind": RESIDENT.name, "status": report["status"], "files": index,
              "archive_sha256": sha256_file(archive), "archive_bytes": archive.stat().st_size,
              "results_sha256": sha256_file(destination / "results.json"),
              "hardware_timing_admitted": False, "original_A4_comparison_complete": False,
              "indexed_not_redistributed": ["SST executable", "DRAMSim3 library", "toolchains"],
              "claim": "portable_resident_prediction_recheck_not_FPGA_calibration_or_A4_comparison"}
    atomic_write_json(destination / "verification.json", record)
    return record


def deliver(run: Path, destination: Path) -> dict:
    if destination.exists():
        raise FileExistsError("fresh model delivery directory required")
    # The legacy contract is copied verbatim, not regenerated from today's code.
    manifest = json.loads((run / "baseline/identity.json").read_text())
    with tarfile.open(run / "source_before.tar.gz", "r:gz") as source:
        with source.extractfile("configs/experiments/grasu_component_refactor_v1.json") as stream:
            contract = stream.read()
    contract_path = run / "baseline/contract.json"
    if contract_path.exists() and contract_path.read_bytes() != contract:
        raise ValueError("refuse to replace the frozen legacy contract")
    if hashlib.sha256(contract).hexdigest() != manifest["contract_sha256"]:
        raise ValueError("pre-edit legacy contract differs")
    if not contract_path.exists():
        contract_path.write_bytes(contract)
    report = recheck(run)
    files = []
    for directory in ("sst", "baseline", "legacy_after"):
        files += raw_files(run / directory, directory)
    for pattern in ("*.json", "*.txt", "*.tar.gz"):
        files += [(path, path.name) for path in sorted(run.glob(pattern)) if path.is_file()]
    files += [(run / "plugin/libspine_cycle.so", "plugin/libspine_cycle.so"),
              (run / "core/Testing/Temporary/LastTest.log", "core/Testing/Temporary/LastTest.log"),
              (run / "core/CMakeCache.txt", "core/CMakeCache.txt")]
    for pattern in ("flags.make", "link.txt"):
        files += [(path, path.relative_to(run).as_posix()) for path in sorted((run / "core").rglob(pattern))]
    destination.mkdir(parents=True)
    archive = destination / "raw_model.tar.gz"
    index = seal(files, archive)
    atomic_write_json(destination / "results.json", report)
    result = {"schema_version": 1, "status": report["status"], "files": index,
              "archive_sha256": sha256_file(archive), "archive_bytes": archive.stat().st_size,
              "results_sha256": sha256_file(destination / "results.json"),
              "hardware_timing_admitted": False, "original_A4_comparison_complete": False,
              "indexed_not_redistributed": ["SST executable", "DRAMSim3 library", "toolchains", "historical plugin"],
              "claim": "portable_raw_recheck_not_a_new_simulation_or_FPGA_calibration"}
    atomic_write_json(destination / "verification.json", result)
    return result


def verify(destination: Path) -> dict:
    record = json.loads((destination / "verification.json").read_text())
    kind = record.get("package_kind", "legacy_and_smoke")
    if kind not in ("legacy_and_smoke", RESIDENT.name):
        raise ValueError("unknown model evidence package kind")
    max_bytes = (1024 if kind == RESIDENT.name else 128) * 1024**2
    archive = destination / "raw_model.tar.gz"
    if (sha256_file(archive) != record["archive_sha256"] or archive.stat().st_size != record["archive_bytes"]
            or sha256_file(destination / "results.json") != record["results_sha256"]):
        raise ValueError("sealed model evidence differs")
    entries = record["files"]
    expected = {row["path"]: row for row in entries}
    if (len(expected) != len(entries) or sum(row["bytes"] for row in entries) > max_bytes
            or any(Path(name).is_absolute() or ".." in Path(name).parts for name in expected)):
        raise ValueError("unsafe or duplicate evidence index")
    with tempfile.TemporaryDirectory() as temporary, tarfile.open(archive, "r:gz") as stream:
        members = stream.getmembers()
        if len(members) != len(entries) or {row.name for row in members} != expected.keys():
            raise ValueError("evidence archive membership differs")
        root = Path(temporary)
        for member in members:
            item = expected[member.name]
            if not member.isfile() or member.size != item["bytes"]:
                raise ValueError("evidence member type or size differs")
            with stream.extractfile(member) as content:
                data = content.read()
            if hashlib.sha256(data).hexdigest() != item["sha256"]:
                raise ValueError("evidence member hash differs")
            path = root / member.name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(data)
        if kind == RESIDENT.name:
            if read_json(root / "sst/manifest.json").get("study_scope") != RESIDENT.name:
                raise ValueError("resident evidence scope differs")
            report = recheck_study(root / "sst", root / "plugin/libspine_cycle.so")
        else:
            report = recheck(root)
    if (not same_typed(report, json.loads((destination / "results.json").read_text()))
            or record["status"] != report["status"] or record["hardware_timing_admitted"] is not False
            or record["original_A4_comparison_complete"] is not False):
        raise ValueError("sealed model conclusion differs")
    return report


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run", type=Path)
    parser.add_argument("--destination", type=Path, required=True)
    parser.add_argument("--verify-only", action="store_true")
    parser.add_argument("--resident-only", action="store_true")
    parser.add_argument("--plugin", type=Path, help="isolated plugin file for resident-only delivery")
    args = parser.parse_args()
    if args.verify_only:
        result = verify(args.destination.resolve())
    elif args.run:
        if args.resident_only:
            if not args.plugin:
                parser.error("--plugin is required with --resident-only")
            result = deliver_resident(args.run.resolve(), args.plugin.resolve(), args.destination.resolve())
        else:
            result = deliver(args.run.resolve(), args.destination.resolve())
        verify(args.destination.resolve())
    else:
        parser.error("--run is required for delivery")
    print(json.dumps({"status": result["status"], "portable_recheck": "PASS"}))


if __name__ == "__main__":
    main()
