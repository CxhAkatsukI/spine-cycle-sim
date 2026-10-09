"""Isolate exact two-guard patches; compile real host APIs without launching a device."""

import json
from pathlib import Path
import shutil
import subprocess

from spine_cycle_sim.experiments.campaign_runtime import atomic_write_json, sha256_file
from ..preparation import author_snapshot
from .fixtures import NAMES


def validate(contract):
    expected = {"schema_version": 1, "cases": list(NAMES), "variants": ["original", "row_guard", "both_guards"],
        "segment_slots": 16, "hot_segments_per_half": 131072, "repetitions": 2, "instrument_all_cases": True,
        "memory_limit_gib": 4, "reserve_gib": 16, "compile_timeout_seconds": 300, "run_timeout_seconds": 300}
    for key, value in expected.items():
        if json.dumps(contract.get(key)) != json.dumps(value): raise ValueError("G host fixed contract changed: " + key)


def prepare(root: Path, source: Path, output: Path, contract: dict):
    author = author_snapshot(root, source); original = source / "GraSU/GraSU/src"
    if sha256_file(original / "pma_dynamic_graph.hpp") != contract["original_header_sha256"]: raise ValueError("G original PMA header changed")
    records = []
    for variant, patches in (("original", ()), ("row_guard", ("row",)), ("both_guards", ("row", "initial"))):
        target = output / variant; target.mkdir(parents=True)
        for name in ("host.cpp", "config.h", "kernel_config.h", "pma_dynamic_graph.hpp"): shutil.copyfile(original / name, target / name)
        applied = []
        for kind in patches:
            patch = root / f"configs/experiments/patches/grasu_host_{kind}_bounds_v1.patch"
            command = ["patch", "--batch", "--forward", "-p1", "--input", str(patch)]
            for command in (command + ["--dry-run"], command):
                result = subprocess.run(command, cwd=target, capture_output=True, text=True, timeout=30)
                if result.returncode: raise ValueError("G reviewed patch failed: " + result.stderr)
            applied.append({"path": str(patch.relative_to(root)), "sha256": sha256_file(patch)})
        diff = subprocess.run(["git", "diff", "--no-index", str(original / "pma_dynamic_graph.hpp"), str(target / "pma_dynamic_graph.hpp")],
            capture_output=True, text=True, timeout=30)
        if diff.returncode not in (0, 1): raise ValueError("G header diff failed")
        changed = [line for line in diff.stdout.splitlines() if line.startswith(("+", "-")) and not line.startswith(("+++", "---"))]
        if len(changed) != len(patches) * 2: raise ValueError("G header patch was skipped or changed undeclared lines")
        (target / "compatibility.diff").write_text(diff.stdout)
        records.append({"id": variant, "directory": str(target), "patches": applied, "source": author,
            "files": [{"path": str(path), "sha256": sha256_file(path)} for path in sorted(target.iterdir())]})
    atomic_write_json(output / "variants.json", records); return records


def identities(root: Path):
    paths = [root / name for name in ("scripts/run_original_grasu_host.py", "tests/test_original_grasu_host.py",
        "configs/experiments/original_grasu_host_v1.json", "cpp/tests/publication_sources/grasu_host_probe.cpp")]
    paths += sorted((root / "cpp/tests/publication_sources/grasu_host").glob("*.hpp"))
    paths += sorted((root / "spine_cycle_sim/experiments/upstream_controls/grasu/host").glob("*.py"))
    paths += sorted((root / "configs/experiments/patches").glob("grasu_host_*_bounds_v1.patch"))
    paths += [root / "spine_cycle_sim/experiments/upstream_controls" / name for name in ("execution.py", "sources.py")]
    paths += [root / "spine_cycle_sim/experiments/upstream_controls/grasu" / name for name in ("preparation.py", "analysis.py")]
    paths += [root / "spine_cycle_sim/experiments/campaign_runtime.py", root / "cpp/tests/publication_sources/probe_support.hpp"]
    paths += [root / "cpp/tests/publication_sources/grasu_path" / name for name in ("fixture.hpp", "lookup.hpp")]
    return [{"path": str(path.relative_to(root)), "sha256": sha256_file(path)} for path in sorted(paths)]


def compiler_command(root: Path, source: Path, prepared: Path, include: Path, xrt: Path, output: Path, compiler: str, instrumented=False):
    command = [compiler, "-std=c++17", "-O1", "-g0", "-D_GLIBCXX_ASSERTIONS", "-ffunction-sections", "-fdata-sections",
        "-Wno-unknown-pragmas", "-Wno-deprecated-declarations", "-DDISABLE_MAX_HLS_STREAM_DEPTH_PRINT",
        "-MD", "-MF", str(output / "dependencies.d"), "-MT", "probe", f"-I{prepared}", f"-I{source / 'GraSU/GraSU_kernels/src'}",
        f"-I{include}", f"-I{include / 'etc'}", f"-I{xrt}"]
    if instrumented: command += ["-fsanitize=undefined", "-fno-sanitize-recover=all"]
    return command + [str(root / "cpp/tests/publication_sources/grasu_host_probe.cpp"), "-Wl,--gc-sections", "-lOpenCL", "-pthread", "-lgmp", "-o", str(output / "probe")]
