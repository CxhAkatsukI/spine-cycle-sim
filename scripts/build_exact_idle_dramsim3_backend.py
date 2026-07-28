#!/usr/bin/env python3
"""Build an isolated SST/DRAMSim3 backend with exact idle-clock advance."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import tarfile


ROOT = Path(__file__).resolve().parents[1]
DRAMSIM3_REVISION = "29817593b3389f1337235d63cac515024ab8fd6e"


def run(command: list[str], *, cwd: Path, env: dict[str, str] | None = None) -> None:
    print("+", " ".join(command), flush=True)
    subprocess.run(command, cwd=cwd, env=env, check=True)


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--dramsim3-repo",
        type=Path,
        default=Path("/data/feiyang/sst-build/DRAMsim3"),
    )
    parser.add_argument(
        "--sst-elements-archive",
        type=Path,
        default=Path("/data/feiyang/sst-build/sstelements-16.0.0.tar.gz"),
    )
    parser.add_argument(
        "--sst-core-prefix", type=Path, default=Path("/data/feiyang/sst")
    )
    parser.add_argument("--work-root", type=Path, required=True)
    parser.add_argument("--install-prefix", type=Path, required=True)
    parser.add_argument("--jobs", type=int, default=8)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    if args.jobs <= 0:
        raise SystemExit("--jobs must be positive")
    work_root = args.work_root.resolve()
    install_prefix = args.install_prefix.resolve()
    if work_root.exists() and any(work_root.iterdir()):
        raise SystemExit(f"work root must be new or empty: {work_root}")
    work_root.mkdir(parents=True, exist_ok=True)
    install_prefix.mkdir(parents=True, exist_ok=True)

    dramsim3 = work_root / "dramsim3"
    run(
        ["git", "clone", "--no-checkout", str(args.dramsim3_repo.resolve()), str(dramsim3)],
        cwd=work_root,
    )
    run(["git", "checkout", "--detach", DRAMSIM3_REVISION], cwd=dramsim3)
    run(
        ["git", "apply", str(ROOT / "patches/dramsim3_exact_idle_advance.patch")],
        cwd=dramsim3,
    )
    run(
        ["git", "apply", str(ROOT / "patches/dramsim3_active_queue_hotpath.patch")],
        cwd=dramsim3,
    )
    run(
        ["git", "apply", str(ROOT / "patches/dramsim3_stats_hotpath.patch")],
        cwd=dramsim3,
    )

    sst_extract = work_root / "sst-elements-source"
    sst_extract.mkdir()
    with tarfile.open(args.sst_elements_archive.resolve(), "r:gz") as archive:
        archive.extractall(sst_extract, filter="data")
    candidates = [
        path.parent for path in sst_extract.rglob("configure") if path.is_file()
    ]
    if len(candidates) != 1:
        raise SystemExit(f"expected one SST elements source root, found {candidates}")
    sst_elements = candidates[0]
    run(
        ["patch", "-p1", "-i", str(ROOT / "patches/sst_elements_dramsim3_idle_clock.patch")],
        cwd=sst_elements,
    )

    dramsim_build = work_root / "dramsim3-build"
    run(
        [
            "cmake",
            "-S",
            str(dramsim3),
            "-B",
            str(dramsim_build),
            "-DCMAKE_POLICY_VERSION_MINIMUM=3.5",
            "-DCMAKE_BUILD_TYPE=Release",
            "-DCMAKE_SHARED_LINKER_FLAGS=-static-libstdc++ -static-libgcc -Wl,--exclude-libs,ALL",
        ],
        cwd=work_root,
    )
    run(
        ["cmake", "--build", str(dramsim_build), "--target", "dramsim3", f"-j{args.jobs}"],
        cwd=work_root,
    )

    harness = work_root / "dramsim3_idle_advance_equivalence"
    run(
        [
            "g++",
            "-std=c++11",
            "-O2",
            str(ROOT / "cpp/tests/dramsim3_idle_advance_equivalence.cpp"),
            f"-I{dramsim3 / 'src'}",
            f"-L{dramsim3}",
            f"-Wl,-rpath,{dramsim3}",
            "-ldramsim3",
            "-o",
            str(harness),
        ],
        cwd=work_root,
    )
    ab_root = work_root / "dramsim3-ab"
    baseline = ab_root / "baseline"
    skipped = ab_root / "skipped"
    baseline.mkdir(parents=True)
    skipped.mkdir(parents=True)
    run(
        [
            str(harness),
            str(dramsim3 / "configs/HBM2_4Gb_x128.ini"),
            f"{baseline}/",
            f"{skipped}/",
        ],
        cwd=dramsim3,
    )
    for filename in ("dramsim3.json", "dramsim3epoch.json"):
        if (baseline / filename).read_bytes() != (skipped / filename).read_bytes():
            raise SystemExit(f"DRAMSim3 A/B mismatch: {filename}")

    sst_build = work_root / "sst-elements-build"
    sst_build.mkdir()
    sst_core = args.sst_core_prefix.resolve()
    configure_env = os.environ.copy()
    configure_env["LDFLAGS"] = " ".join(
        (
            f"-Wl,-rpath,{sst_core / 'pylib'}",
            f"-Wl,-rpath,{sst_core / 'lib'}",
            f"-Wl,-rpath,{sst_core / 'lib/sst-core'}",
            f"-Wl,-rpath,{dramsim3}",
        )
    )
    run(
        [
            str(sst_elements / "configure"),
            f"--prefix={install_prefix}",
            f"--with-sst-core={sst_core}",
            f"--with-dramsim3={dramsim3}",
        ],
        cwd=sst_build,
        env=configure_env,
    )
    mem_build = sst_build / "src/sst/elements/memHierarchy"
    run(["make", f"-j{args.jobs}"], cwd=mem_build)
    run(["make", "install-compLTLIBRARIES"], cwd=mem_build)

    mem_library = install_prefix / "lib/sst-elements-library/libmemHierarchy.so"
    if not mem_library.is_file():
        raise SystemExit(f"missing installed SST element: {mem_library}")
    evidence = {
        "schema_version": 1,
        "dramsim3_revision": DRAMSIM3_REVISION,
        "dramsim3_patch_sha256": sha256(
            ROOT / "patches/dramsim3_exact_idle_advance.patch"
        ),
        "dramsim3_active_queue_patch_sha256": sha256(
            ROOT / "patches/dramsim3_active_queue_hotpath.patch"
        ),
        "dramsim3_stats_hotpath_patch_sha256": sha256(
            ROOT / "patches/dramsim3_stats_hotpath.patch"
        ),
        "sst_elements_version": "16.0.0",
        "sst_patch_sha256": sha256(
            ROOT / "patches/sst_elements_dramsim3_idle_clock.patch"
        ),
        "dramsim3_library": str((dramsim3 / "libdramsim3.so").resolve()),
        "memhierarchy_library": str(mem_library.resolve()),
        "dramsim3_ab_final_sha256": sha256(baseline / "dramsim3.json"),
        "dramsim3_ab_epoch_sha256": sha256(baseline / "dramsim3epoch.json"),
        "status": "PASS",
    }
    (work_root / "build_evidence.json").write_text(
        json.dumps(evidence, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    print(json.dumps(evidence, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
