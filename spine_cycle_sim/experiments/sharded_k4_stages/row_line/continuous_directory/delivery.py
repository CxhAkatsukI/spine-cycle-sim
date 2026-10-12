"""Seal a rejected candidate with its positive functional gates and negative timing."""

import argparse
import json
from pathlib import Path
import shutil

from spine_cycle_sim.experiments.campaign_runtime import atomic_write_json, sha256_file
from spine_cycle_sim.experiments.original_regraph_execution.sssp_real_round.delivery import seal
from spine_cycle_sim.experiments.original_regraph_validation.analysis import same_typed
from ..delivery import raw_files
from ..model_archive import extracted
from .recheck import read, recheck
from .archive_parts import ARCHIVE, assembled, split
from .study import ROOT


def selected(model, hls, regression, basis, legacy_basis, pre_edit):
    files = []
    for run, prefix, directories in (
        (model, "model", ("raw", "inputs", "states")),
        (hls, "hls", ("reference", "candidate", "functional")),
        (regression, "regression", ("legacy-after",)),
        (legacy_basis, "legacy_basis", ("cases", "campaign")),
    ):
        for directory in directories:
            if (run / directory).exists():
                files += raw_files(run / directory, prefix + "/" + directory)
        for path in sorted(run.glob("*")):
            if path.is_file() and path.suffix in {".json", ".txt", ".gz"}:
                files.append((path, prefix + "/" + path.name))
    for pin in read(model / "results.json")["build_files"]:
        path = Path(pin["path"])
        files.append((path, "model/build/" + path.relative_to(model / "build").as_posix()))
    # Keep schedules and logs, not proprietary compiler intermediates.
    for path in sorted((hls / "production").rglob("*")):
        relative = path.relative_to(hls / "production")
        if path.is_symlink():
            raise ValueError("symlinked production evidence")
        if path.is_file() and (path.suffix in {".xml", ".rpt"} or
                               ("build" not in relative.parts and
                                path.suffix in {".xo", ".json", ".txt", ".log"})):
            files.append((path, "hls/production/" + path.relative_to(hls / "production").as_posix()))
    reference = Path(read(hls / "manifest.json")["sources"][-1]["path"])
    files.append((reference, "reference.xo"))
    for name in ("results.json", "manifest.json"):
        files.append((basis / name, "basis/" + name))
    for path in sorted((basis / "raw").glob("*.stdout.txt")):
        if path.stem.endswith(("original.stdout", "cross_row.stdout")):
            files.append((path, "basis/raw/" + path.name))
    files += [(regression / "plugin/libspine_cycle.so", "regression/plugin/libspine_cycle.so"),
              (regression / "core/Testing/Temporary/LastTest.log", "regression/core/Testing/Temporary/LastTest.log"),
              (regression / "core/CMakeCache.txt", "regression/core/CMakeCache.txt"),
              (ROOT / "configs/experiments/grasu_component_refactor_v1.json", "regression/contract.json")]
    for path in sorted(pre_edit.glob("pre_edit_*.tar.gz")):
        files.append((path, "pre_edit/" + path.name))
    for path in sorted(Path(__file__).parent.glob("*.py")):
        files.append((path, "review_code/" + path.name))
    test = ROOT / "tests/test_sharded_k4_continuous_directory.py"
    files.append((test, "review_code/tests/" + test.name))
    historical = ROOT / "spine_cycle_sim/experiments/sharded_k4_stages/row_line/cross_row/a4_control/resources.py"
    files.append((historical, "review_code/historical_audit/resources.py"))
    test = ROOT / "tests/test_sharded_k4_cross_row_a4_resources.py"
    files.append((test, "review_code/tests/" + test.name))
    unique = {}
    for path, name in files:
        if path.is_symlink():
            raise ValueError("symlinked evidence")
        if name in unique and unique[name] != path:
            raise ValueError("conflicting archive path")
        unique[name] = path
    return [(path, name) for name, path in sorted(unique.items())]


def deliver(model, hls, regression, basis, legacy_basis, pre_edit, destination):
    if destination.exists():
        raise FileExistsError("fresh evidence destination required")
    destination.mkdir(parents=True)
    archive = destination / "raw_continuous_directory.tar.gz"
    index = seal(selected(model, hls, regression, basis, legacy_basis, pre_edit), archive)
    record = {"schema": 1, "files": index, "archive_bytes": archive.stat().st_size,
              "archive_sha256": sha256_file(archive)}
    with extracted(archive, record, max_bytes=512 * 1024**2) as root:
        result = recheck(root)
    atomic_write_json(destination / "results.json", result)
    record.update(status=result["status"], results_sha256=sha256_file(destination / "results.json"),
                  portable_raw_recheck=True, claim="rejected_nominal_schedule_not_FPGA_performance",
                  indexed_not_redistributed=["proprietary tool executables", "compiled xsim runtime"])
    atomic_write_json(destination / "verification.json", record)
    return result


def verify(destination):
    record = read(destination / "verification.json")
    if sha256_file(destination / "results.json") != record["results_sha256"]:
        raise ValueError("sealed conclusion differs")
    with assembled(destination, record) as archive, extracted(archive, record, max_bytes=512 * 1024**2) as root:
        result = recheck(root)
    if not same_typed(result, read(destination / "results.json")) or record["status"] != result["status"]:
        raise ValueError("portable conclusion differs")
    return result


def publish(source, destination):
    verify(source)
    record = read(source / "verification.json")
    if "archive_parts" in record:
        raise ValueError("publish requires the original unsplit sealed archive")
    record["archive_parts"] = split(source / ARCHIVE, destination)
    shutil.copyfile(source / "results.json", destination / "results.json")
    atomic_write_json(destination / "verification.json", record)
    return verify(destination)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--destination", type=Path, required=True)
    parser.add_argument("--verify-only", action="store_true")
    parser.add_argument("--publish-from", type=Path,
                        help="Publish an already sealed local delivery as lossless bounded parts")
    for name in ("model", "hls", "regression", "basis", "legacy-basis", "pre-edit"):
        parser.add_argument("--" + name, type=Path)
    args = parser.parse_args()
    if args.publish_from:
        if args.verify_only:
            parser.error("--publish-from and --verify-only are mutually exclusive")
        publish(args.publish_from.resolve(), args.destination.resolve())
    elif not args.verify_only:
        required = ("model", "hls", "regression", "basis", "legacy_basis", "pre_edit")
        if any(getattr(args, name) is None for name in required):
            parser.error("all run/basis/pre-edit paths required for delivery")
        deliver(**{name: getattr(args, name).resolve() for name in required}, destination=args.destination.resolve())
    result = verify(args.destination.resolve())
    print(json.dumps({"status": result["status"], "portable_raw_recheck": "PASS"}))


if __name__ == "__main__":
    main()
