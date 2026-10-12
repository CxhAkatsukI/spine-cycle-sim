"""Seal and independently recompute the finite-reader prediction study."""

import argparse
import json
from pathlib import Path
import shutil

from spine_cycle_sim.experiments.campaign_runtime import atomic_write_json, sha256_file
from spine_cycle_sim.experiments.original_regraph_execution.sssp_real_round.delivery import seal
from spine_cycle_sim.experiments.original_regraph_validation.analysis import same_typed
from ..model_archive import extracted
from ..continuous_directory.archive_parts import assembled, split
from .recheck import read, recheck
from .selection import selected

ARCHIVE = "raw_directory_tile.tar.gz"


def deliver(model, hls, regression, basis, legacy_basis, study, destination):
    destination.mkdir(parents=True, exist_ok=False)
    archive = destination / ARCHIVE
    entries = seal(selected(model, hls, regression, basis, legacy_basis, study), archive)
    if archive.stat().st_size > 512 * 1024**2:
        raise ValueError("archive exceeds bounded multipart transport size; preserve local archive")
    record = {"schema": 1, "files": entries, "archive_bytes": archive.stat().st_size,
              "archive_sha256": sha256_file(archive)}
    with extracted(archive, record, max_bytes=1024**3) as root:
        result = recheck(root)
    atomic_write_json(destination / "results.json", result)
    record.update(status=result["status"], results_sha256=sha256_file(destination / "results.json"),
                  portable_raw_recheck=True, claim="finite_integrated_path_prediction_not_FPGA",
                  indexed_not_redistributed=["proprietary tool executables", "compiled xsim runtime",
                      "intermediate checkpoint binaries and repeated state matrices"])
    atomic_write_json(destination / "verification.json", record)
    return result


def verify(destination):
    record = read(destination / "verification.json")
    if sha256_file(destination / "results.json") != record["results_sha256"]:
        raise ValueError("sealed conclusion differs")
    with assembled(destination, record, archive_name=ARCHIVE) as archive, \
            extracted(archive, record, max_bytes=1024**3) as root:
        result = recheck(root)
    if not same_typed(result, read(destination / "results.json")) or record["status"] != result["status"]:
        raise ValueError("portable conclusion differs")
    return result


def publish(source, destination):
    verify(source)
    record = read(source / "verification.json")
    if "archive_parts" in record:
        raise ValueError("publish requires the original unsplit sealed archive")
    record["archive_parts"] = split(source / ARCHIVE, destination, archive_name=ARCHIVE)
    shutil.copyfile(source / "results.json", destination / "results.json")
    atomic_write_json(destination / "verification.json", record)
    return verify(destination)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--destination", type=Path, required=True)
    parser.add_argument("--verify-only", action="store_true")
    parser.add_argument("--publish-from", type=Path)
    names = ("model", "hls", "regression", "basis", "legacy-basis", "study")
    for name in names:
        parser.add_argument("--" + name, type=Path)
    args = parser.parse_args()
    if args.publish_from:
        if args.verify_only:
            parser.error("--publish-from and --verify-only are mutually exclusive")
        publish(args.publish_from.resolve(), args.destination.resolve())
    elif not args.verify_only:
        keys = [name.replace("-", "_") for name in names]
        if any(getattr(args, key) is None for key in keys):
            parser.error("all run and basis paths required for delivery")
        deliver(**{key: getattr(args, key).resolve() for key in keys}, destination=args.destination.resolve())
    result = verify(args.destination.resolve())
    print(json.dumps({"status": result["status"], "portable_raw_recheck": "PASS"}))


if __name__ == "__main__":
    main()
