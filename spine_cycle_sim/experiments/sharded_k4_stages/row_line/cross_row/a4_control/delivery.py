"""Seal and recheck the complete versioned A4 control, without replacing old evidence."""

import argparse
import json
from pathlib import Path
import shutil

from spine_cycle_sim.experiments.campaign_runtime import atomic_write_json, sha256_file
from spine_cycle_sim.experiments.original_regraph_execution.sssp_real_round.delivery import seal
from spine_cycle_sim.experiments.original_regraph_validation.analysis import same_typed
from ...evidence import bounded
from ...model_archive import extracted
from .contract import LIMITS
from .recheck import read, recheck


def watchdog(run, path=None):
    path = path or run.with_name(run.name + "_watchdog.resources.json")
    manifest = read(run / "manifest.json")
    record = read(path)
    expected = [manifest["python_executable"], "-m", __package__ + ".study", "--worker", "--output",
                manifest["output"], "--pre-edit"]
    if record["command"][:-1] != expected:
        raise ValueError("aggregate watchdog command differs")
    return bounded(path, record["command"], manifest["root"], LIMITS["outer_timeout_seconds"], LIMITS["outer_tree_gib"])


def deliver(run, destination):
    if destination.exists():
        raise FileExistsError("fresh control delivery required")
    report, guard = recheck(run), watchdog(run)
    names = ["manifest.json", "results.json", "pre_edit_source.tar.gz", "pre_edit_source_index.json"]
    names += [item["relative"] for item in report["build_files"]]
    files = [(run / name, "run/" + name) for name in names]
    for name in ("sources", "bases", "inputs", "expected", "states", "raw"):
        for path in sorted((run / name).rglob("*")):
            if path.is_symlink():
                raise ValueError("symlinked raw evidence")
            if path.is_file():
                files.append((path, "run/" + str(path.relative_to(run))))
    files += [(run.with_name(run.name + "_watchdog." + suffix), "watchdog/" + suffix)
              for suffix in ("resources.json", "stdout.txt", "stderr.txt")]
    destination.mkdir(parents=True)
    archive = destination / "raw_cross_row_A4.tar.gz"
    index = seal(files, archive)
    shutil.copyfile(run / "results.json", destination / "results.json")
    record = {"status": report["status"], "files": index, "archive_sha256": sha256_file(archive),
              "archive_bytes": archive.stat().st_size, "results_sha256": sha256_file(destination / "results.json"),
              "aggregate_watchdog": guard, "scope": report["admission"],
              "claim": "structural_one_round_diagnostic_not_publication_or_hardware_match"}
    atomic_write_json(destination / "verification.json", record)
    return record


def verify(destination):
    record = read(destination / "verification.json")
    if sha256_file(destination / "results.json") != record["results_sha256"]:
        raise ValueError("sealed summary differs")
    with extracted(destination / "raw_cross_row_A4.tar.gz", record, max_bytes=512 * 1024**2) as root:
        report = recheck(root / "run")
        guard = watchdog(root / "run", root / "watchdog/resources.json")
    if (not same_typed(report, read(destination / "results.json"))
            or not same_typed(guard, record["aggregate_watchdog"])
            or record["status"] != report["status"] or record["scope"] != report["admission"]):
        raise ValueError("portable raw conclusion differs")
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run", type=Path)
    parser.add_argument("--destination", type=Path, required=True)
    parser.add_argument("--verify-only", action="store_true")
    args = parser.parse_args()
    if not args.verify_only:
        if not args.run:
            parser.error("--run required for delivery")
        deliver(args.run.resolve(), args.destination.resolve())
    print(json.dumps({"status": verify(args.destination.resolve())["status"], "portable_raw_recheck": "PASS"}))


if __name__ == "__main__":
    main()
