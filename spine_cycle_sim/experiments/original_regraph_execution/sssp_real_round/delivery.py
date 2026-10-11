"""Package admitted states, inputs and raw logs; leave large external tools indexed."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import shutil
import tarfile

from spine_cycle_sim.experiments.campaign_runtime import atomic_write_json, sha256_file
from .recheck import recheck


def members(directory: Path, prefix: str) -> list[tuple[Path, str]]:
    if not directory.is_dir() or directory.is_symlink():
        raise ValueError("missing or symlinked evidence directory")
    files = []
    for path in sorted(directory.rglob("*")):
        if path.is_symlink():
            raise ValueError("symlink in evidence directory")
        if path.is_file():
            relative = path.relative_to(directory)
            if (path.suffix not in {".json", ".txt", ".u32le"}
                    or path.name == "dirty.diff"):
                raise ValueError("unexpected file in raw evidence: " + str(relative))
            files.append((path, prefix + "/" + relative.as_posix()))
    return files


def seal(files: list[tuple[Path, str]], archive: Path) -> list[dict]:
    names = [name for _, name in files]
    if len(set(names)) != len(names) or any(Path(name).is_absolute() or ".." in Path(name).parts for name in names):
        raise ValueError("duplicate or unsafe archive member")
    if archive.exists():
        raise ValueError("refuse to overwrite evidence archive")
    index = [{"path": name, "bytes": path.stat().st_size, "sha256": sha256_file(path)} for path, name in files]
    with tarfile.open(archive, "w:gz") as bundle:
        for path, name in files:
            bundle.add(path, arcname=name, recursive=False)
    with tarfile.open(archive, "r:gz") as bundle:
        if bundle.getnames() != names:
            raise ValueError("archive membership changed")
        for item in index:
            with bundle.extractfile(item["path"]) as stream:
                if hashlib.sha256(stream.read()).hexdigest() != item["sha256"]:
                    raise ValueError("archive member changed")
    if any(sha256_file(path) != item["sha256"] for (path, _), item in zip(files, index, strict=True)):
        raise ValueError("raw evidence changed while packaging")
    return index


def deliver(root: Path, run: Path, destination: Path, components: Path, whole: Path,
            verification: Path, attempts: list[Path]) -> dict:
    if destination.exists():
        raise ValueError("use a fresh evidence delivery directory")
    report, references = recheck(root, run, components, whole)
    for attempt in attempts:
        if json.loads((attempt / "results.json").read_text())["status"] != "failed":
            raise ValueError("failed-attempt archive contains nonfailed experiment")
    for name in ("build_all", "ctest", "python"):
        record = json.loads((verification / (name + ".resources.json")).read_text())
        if record["exit_code"] or record.get("timed_out") or record.get("stop_reason", "process_exit") != "process_exit":
            raise ValueError("final verification did not pass")
    files = []
    for directory, prefix in [(run, "run"), (components, "component_baseline"), (whole, "whole_baseline"),
                              (verification, "verification"), *[(path, "attempts/" + path.name) for path in attempts]]:
        files.extend(members(directory, prefix))
    destination.mkdir(parents=True)
    archive = destination / "raw_sssp_real_round.tar.gz"
    index = seal(files, archive)
    shutil.copyfile(run / "results.json", destination / "results.json")
    record = {"schema_version": 1, "status": report["status"], "files": index,
              "archive_bytes": archive.stat().st_size, "archive_sha256": sha256_file(archive),
              "results_sha256": sha256_file(destination / "results.json"),
              "complete_raw_inputs_states_counters_and_legacy_equality_rechecked": True,
              "archived": ["complete_SSSP_inputs_and_seven_state_replicas", "complete_old_PR_state_replicas",
                           "failed_attempts", "resource_and_verification_logs"],
              "external_references": references,
              "indexed_not_archived": ["compiled_binaries", "pinned_author_probe_and_dependencies", "local_HLS_UDF_and_synthesis_RTL"],
              "scope": report["admission"]}
    atomic_write_json(destination / "verification.json", record)
    return record


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    for flag in ("run", "destination", "component-baseline", "whole-baseline", "verification"):
        parser.add_argument("--" + flag, type=Path, required=True)
    parser.add_argument("--attempt", type=Path, action="append", default=[])
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[4]
    record = deliver(root, args.run.resolve(), args.destination.resolve(), args.component_baseline.resolve(),
                     args.whole_baseline.resolve(), args.verification.resolve(), [p.resolve() for p in args.attempt])
    print(json.dumps({"status": record["status"], "archive_bytes": record["archive_bytes"]}, sort_keys=True))


if __name__ == "__main__":
    main()
