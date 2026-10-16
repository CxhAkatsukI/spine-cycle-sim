"""Seal fullgraph preparation logs and replay them from a portable archive."""

import argparse
import hashlib
import json
from pathlib import Path, PurePosixPath
import tarfile

from spine_cycle_sim.experiments.campaign_runtime import atomic_write_json, sha256_file
from spine_cycle_sim.experiments.original_regraph_execution.sssp_real_round.delivery import seal
from . import preparation
from .recheck import recheck

LIMIT = 64 * 1024**2


def selected(attempt, report):
    files = {"results.json": attempt / "results.json"}
    for directory in ("source", "raw"):
        for path in sorted((attempt / directory).rglob("*")):
            if path.is_symlink():
                raise ValueError("symlinks are not preparation evidence")
            if path.is_file():
                files[path.relative_to(attempt).as_posix()] = path
    for pattern in ("*.smoke.graph", "*.d"):
        files.update((path.name, path) for path in sorted(attempt.glob(pattern)))
    for pin in report["pins"]:
        path = Path(pin["path"])
        if "spine_cycle_sim" in path.parts:
            relative = Path(*path.parts[path.parts.index("spine_cycle_sim"):])
            name = "runner/" + relative.as_posix()
            if name in files and files[name] != path:
                raise ValueError("ambiguous frozen runner path")
            files[name] = path
    if any(path.is_symlink() or not path.is_file() for path in files.values()):
        raise ValueError("regular archived evidence required")
    if sum(path.stat().st_size for path in files.values()) > LIMIT:
        raise ValueError("preparation capsule exceeds 64 MiB; large graphs and tools stay indexed")
    return files


def deliver(attempts, destination):
    if destination.exists() or len(set(attempts)) != len(attempts) or not attempts:
        raise ValueError("fresh destination and unique terminal attempts required")
    files, outcomes, frozen = [], [], []
    for ordinal, attempt in enumerate(attempts):
        if attempt.is_symlink() or not attempt.is_dir():
            raise ValueError("regular attempt directory required")
        report = json.loads((attempt / "results.json").read_text())
        outcome = recheck(report, lambda name: (attempt / name).read_text())
        preparation.unchanged(report["pins"], full=True)
        frozen.extend(report["pins"])
        prefix = "attempts/" + str(ordinal)
        chosen = selected(attempt, report)
        files.extend((path, prefix + "/" + name) for name, path in chosen.items())
        outcomes.append({"prefix": prefix, "original_path": str(attempt), **outcome})
    destination.mkdir(parents=True)
    archive = destination / "raw_fullgraph_readiness.tar.gz"
    members = seal(files, archive)
    preparation.unchanged(frozen, full=True)
    for item, (path, _) in zip(members, files, strict=True):
        item["source_path"] = str(path)
    record = {"schema_version": 1, "scope": "CPU_oracle_and_graph_HBM_layout_only_not_board_timing",
              "attempts": outcomes, "files": members, "archive_sha256": sha256_file(archive),
              "archive_bytes": archive.stat().st_size,
              "indexed_not_archived": ["graph_inputs", "compiled_hosts", "toolchain_and_system_dependencies"],
              "raw_acceptance_replayed": True}
    atomic_write_json(destination / "index.json", record)
    verify(destination)
    return record


def verify(destination):
    record = json.loads((destination / "index.json").read_text())
    archive = destination / "raw_fullgraph_readiness.tar.gz"
    if (record["schema_version"] != 1 or record["raw_acceptance_replayed"] is not True or
            record["scope"] != "CPU_oracle_and_graph_HBM_layout_only_not_board_timing" or
            archive.stat().st_size != record["archive_bytes"] or sha256_file(archive) != record["archive_sha256"]):
        raise ValueError("archive identity or scope differs from index")
    files = record["files"]
    names = [item["path"] for item in files]
    if len(set(names)) != len(names) or any(
            PurePosixPath(name).is_absolute() or ".." in PurePosixPath(name).parts or
            str(PurePosixPath(name)) != name for name in names):
        raise ValueError("unique safe archive members required")
    if sum(item["bytes"] for item in files) > LIMIT:
        raise ValueError("archive exceeds bounded preparation scope")
    contents = {}
    with tarfile.open(archive, "r:gz") as bundle:
        if bundle.getnames() != names:
            raise ValueError("archive membership differs from index")
        for item, member in zip(files, bundle.getmembers(), strict=True):
            if not member.isfile() or member.size != item["bytes"] or not 0 <= member.size <= LIMIT:
                raise ValueError("regular bounded archive member required")
            with bundle.extractfile(member) as stream:
                data = stream.read()
            if hashlib.sha256(data).hexdigest() != item["sha256"]:
                raise ValueError("archive member hash differs from index")
            contents[item["path"]] = data.decode()
    outcomes = record["attempts"]
    if not outcomes or [row["prefix"] for row in outcomes] != ["attempts/" + str(i) for i in range(len(outcomes))]:
        raise ValueError("unique ordered attempt prefixes required")
    for row in outcomes:
        prefix = row["prefix"] + "/"
        report = json.loads(contents[prefix + "results.json"])
        pins = {pin["path"]: pin for pin in report["pins"]}
        if any(pin != pins[pin["path"]] for pin in report["pins"]):
            raise ValueError("conflicting frozen identities for one path")
        archived_paths = {item["source_path"] for item in files if item["path"].startswith(prefix)}
        required = {path for path in pins if "/spine_cycle_sim/" in path or
                    path.startswith(row["original_path"] + "/source/") or
                    (path.startswith(row["original_path"] + "/") and path.endswith(".smoke.graph"))}
        if not required <= archived_paths:
            raise ValueError("frozen source, runner or smoke snapshot missing from archive")
        for item in files:
            if item["path"].startswith(prefix) and item["source_path"] in pins:
                pin = pins[item["source_path"]]
                if item["sha256"] != pin["sha256"] or item["bytes"] != pin["stat"]["st_size"]:
                    raise ValueError("archived snapshot differs from frozen input pin")
        replay = recheck(report, lambda name: contents[prefix + name])
        if replay != {key: value for key, value in row.items() if key not in ("prefix", "original_path")}:
            raise ValueError("archived acceptance differs from delivery index")
    return record


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    build = commands.add_parser("build")
    build.add_argument("--attempt", type=Path, action="append", required=True)
    build.add_argument("--destination", type=Path, required=True)
    check = commands.add_parser("verify")
    check.add_argument("--destination", type=Path, required=True)
    args = parser.parse_args()
    record = (deliver([path.absolute() for path in args.attempt], args.destination.absolute())
              if args.command == "build" else verify(args.destination))
    print(json.dumps({"attempts": record["attempts"], "archive_bytes": record["archive_bytes"]}, sort_keys=True))


if __name__ == "__main__":
    main()
