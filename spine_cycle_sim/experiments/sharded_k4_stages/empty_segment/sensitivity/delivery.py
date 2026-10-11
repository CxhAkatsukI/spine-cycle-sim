"""Seal sensitivity raw logs, full replicas, standalone binary and source snapshots."""

import argparse
import json
from pathlib import Path
import shutil

from spine_cycle_sim.experiments.campaign_runtime import atomic_write_json, sha256_file
from spine_cycle_sim.experiments.original_regraph_execution.sssp_real_round.delivery import seal
from .recheck import recheck


def raw_files(run: Path) -> list[tuple[Path, str]]:
    paths = [run / "results.json", run / "build/CMakeCache.txt",
             run / "build/routed_regraph_empty_segment_round"]
    for directory in ("raw", "states", "sources"):
        paths.extend((run / directory).rglob("*"))
    paths.extend((run / "build").rglob("flags.make"))
    paths.extend((run / "build").rglob("link.txt"))
    files = []
    for path in sorted(set(paths)):
        if path.is_symlink():
            raise ValueError("symlink in sensitivity evidence")
        if path.is_file():
            files.append((path, "run/" + path.relative_to(run).as_posix()))
    for path in sorted(run.parent.glob(run.name + "_watchdog.*")):
        if path.is_symlink() or not path.is_file():
            raise ValueError("invalid sensitivity watchdog evidence")
        files.append((path, "watchdog/" + path.name))
    # Packaging can evolve independently; execution uses its original snapshots.
    files.extend((path, "packaging/" + path.name) for path in sorted(Path(__file__).parent.glob("*.py")))
    return files


def deliver(root: Path, run: Path, destination: Path) -> dict:
    if destination.exists():
        raise FileExistsError("fresh sensitivity delivery required")
    report = recheck(root, run)
    files = raw_files(run)
    destination.mkdir(parents=True)
    archive = destination / "raw_sensitivity.tar.gz"
    entries = seal(files, archive)
    shutil.copyfile(run / "results.json", destination / "results.json")
    verification = {"schema_version": 1, "status": report["status"], "files": entries,
                    "archive_sha256": sha256_file(archive), "archive_bytes": archive.stat().st_size,
                    "results_sha256": sha256_file(destination / "results.json"),
                    "raw_commands_sources_complete_states_and_counters_rechecked": True,
                    "dependency_scope": "input_files_and_author_layout_retained_in_frozen_basis_package",
                    "external_references": [report["basis"], report["production"]],
                    "admission": report["admission"]}
    atomic_write_json(destination / "verification.json", verification)
    return verification


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run", type=Path, required=True)
    parser.add_argument("--destination", type=Path, required=True)
    args = parser.parse_args()
    result = deliver(Path(__file__).resolve().parents[5], args.run.resolve(), args.destination.resolve())
    print(json.dumps({"status": result["status"], "archive_bytes": result["archive_bytes"]}))


if __name__ == "__main__":
    main()
