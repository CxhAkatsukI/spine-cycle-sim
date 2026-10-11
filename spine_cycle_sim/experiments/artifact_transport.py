"""Lossless, hash-checked chunks for archives above the Git file-size limit."""

import argparse
import hashlib
import json
from pathlib import Path

from .campaign_runtime import atomic_write_json, sha256_file

CHUNK_BYTES = 48 * 1024**2


def split(source: Path, directory: Path) -> dict:
    directory.mkdir(parents=True, exist_ok=False)
    original = sha256_file(source)
    parts = []
    with source.open("rb") as stream:
        while data := stream.read(CHUNK_BYTES):
            name = f"part{len(parts):03d}"
            (directory / name).write_bytes(data)
            parts.append({"name": name, "bytes": len(data),
                          "sha256": hashlib.sha256(data).hexdigest()})
    if not parts or sha256_file(source) != original:
        raise ValueError("empty or changing transport source")
    manifest = {"schema_version": 1, "archive_name": source.name,
                "archive_bytes": sum(part["bytes"] for part in parts),
                "archive_sha256": original, "chunk_bytes": CHUNK_BYTES, "parts": parts}
    atomic_write_json(directory / "transport.json", manifest)
    verify(directory)
    return manifest


def verify(directory: Path) -> dict:
    manifest = json.loads((directory / "transport.json").read_text())
    parts = manifest["parts"]
    if (manifest["schema_version"] != 1 or manifest["chunk_bytes"] != CHUNK_BYTES
            or not parts or [part["name"] for part in parts] != [
                f"part{i:03d}" for i in range(len(parts))]
            or any(type(part["bytes"]) is not int or not 0 < part["bytes"] <= CHUNK_BYTES
                   for part in parts)
            or any(part["bytes"] != CHUNK_BYTES for part in parts[:-1])):
        raise ValueError("invalid transport membership or geometry")
    digest = hashlib.sha256()
    total = 0
    for part in parts:
        path = directory / part["name"]
        if path.is_symlink() or path.stat().st_size != part["bytes"] or sha256_file(path) != part["sha256"]:
            raise ValueError("transport part changed")
        with path.open("rb") as stream:
            while data := stream.read(1024**2):
                digest.update(data)
                total += len(data)
    if digest.hexdigest() != manifest["archive_sha256"] or total != manifest["archive_bytes"]:
        raise ValueError("transport archive identity differs")
    return manifest


def join(directory: Path, output: Path) -> dict:
    manifest = verify(directory)
    with output.open("xb") as destination:
        for part in manifest["parts"]:
            with (directory / part["name"]).open("rb") as source:
                while data := source.read(1024**2):
                    destination.write(data)
    if sha256_file(output) != manifest["archive_sha256"]:
        raise ValueError("reassembled archive changed during transport")
    return manifest


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="mode", required=True)
    pack = sub.add_parser("split")
    pack.add_argument("--source", type=Path, required=True)
    pack.add_argument("--directory", type=Path, required=True)
    unpack = sub.add_parser("join")
    unpack.add_argument("--directory", type=Path, required=True)
    unpack.add_argument("--output", type=Path, required=True)
    check = sub.add_parser("verify")
    check.add_argument("--directory", type=Path, required=True)
    args = parser.parse_args()
    result = (split(args.source, args.directory) if args.mode == "split" else
              join(args.directory, args.output) if args.mode == "join" else verify(args.directory))
    print(json.dumps(result, sort_keys=True))


if __name__ == "__main__":
    main()
