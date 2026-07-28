#!/usr/bin/env python3
"""Rebuild an existing patched DRAMSim3 tree for PGO training or use."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import subprocess


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--build-dir", type=Path, required=True)
    parser.add_argument("--profile-dir", type=Path, required=True)
    parser.add_argument("--mode", choices=("generate", "use"), required=True)
    parser.add_argument("--jobs", type=int, default=8)
    parser.add_argument(
        "--portable-host",
        action="store_true",
        help="omit -march=native from the DRAMSim3 host build",
    )
    parser.add_argument(
        "--evidence",
        type=Path,
        help="optional JSON build-provenance output",
    )
    return parser.parse_args()


def run(command: list[str], *, cwd: Path) -> None:
    print("+", " ".join(command), flush=True)
    subprocess.run(command, cwd=cwd, check=True)


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def main() -> int:
    args = parse_args()
    if args.jobs <= 0:
        raise SystemExit("--jobs must be positive")
    source = args.source.resolve()
    build_dir = args.build_dir.resolve()
    profile_dir = args.profile_dir.resolve()
    if not (source / "CMakeLists.txt").is_file():
        raise SystemExit(f"DRAMSim3 source tree is invalid: {source}")
    profile_dir.mkdir(parents=True, exist_ok=True)
    if args.mode == "use" and not next(profile_dir.rglob("*.gcda"), None):
        raise SystemExit(f"no PGO training data under {profile_dir}")

    host_flags = ["-O3", "-DNDEBUG"]
    linker_flags: list[str]
    if args.mode == "generate":
        host_flags.append(f"-fprofile-generate={profile_dir}")
        linker_flags = [f"-fprofile-generate={profile_dir}"]
    else:
        host_flags.extend(
            (
                f"-fprofile-use={profile_dir}",
                "-fprofile-correction",
                "-Wno-error=coverage-mismatch",
                "-flto",
            )
        )
        linker_flags = ["-flto"]
    host_flags.append("-fno-semantic-interposition")
    if not args.portable_host:
        host_flags.append("-march=native")
    linker_flags.extend(
        ("-static-libstdc++", "-static-libgcc", "-Wl,--exclude-libs,ALL")
    )

    run(
        [
            "cmake",
            "-S",
            str(source),
            "-B",
            str(build_dir),
            "-DCMAKE_POLICY_VERSION_MINIMUM=3.5",
            "-DCMAKE_BUILD_TYPE=Release",
            f"-DCMAKE_CXX_FLAGS_RELEASE={' '.join(host_flags)}",
            f"-DCMAKE_SHARED_LINKER_FLAGS={' '.join(linker_flags)}",
        ],
        cwd=source,
    )
    run(
        [
            "cmake",
            "--build",
            str(build_dir),
            "--target",
            "dramsim3",
            "--clean-first",
            f"-j{args.jobs}",
        ],
        cwd=source,
    )

    library = source / "libdramsim3.so"
    if not library.is_file():
        raise SystemExit(f"DRAMSim3 build did not produce {library}")
    evidence = {
        "schema_version": 1,
        "status": "PASS",
        "mode": args.mode,
        "source": str(source),
        "build_dir": str(build_dir),
        "profile_dir": str(profile_dir),
        "profile_files": len(list(profile_dir.rglob("*.gcda"))),
        "portable_host": args.portable_host,
        "host_flags": host_flags,
        "library": str(library),
        "library_sha256": sha256(library),
    }
    print(json.dumps(evidence, indent=2, sort_keys=True))
    if args.evidence is not None:
        evidence_path = args.evidence.resolve()
        evidence_path.parent.mkdir(parents=True, exist_ok=True)
        evidence_path.write_text(
            json.dumps(evidence, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
