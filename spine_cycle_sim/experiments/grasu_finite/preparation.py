"""Prepare fixed source16 inputs and an independently maintained state oracle."""

import array
import json
from pathlib import Path
import struct
import subprocess
import sys

from spine_cycle_sim.experiments.campaign_runtime import atomic_write_json, sha256_file
from ..upstream_controls.grasu.fixtures import SEGMENTS, HOT, EMPTY, batches, base, edge, final_state, source


def identities(root):
    paths = [root / name for name in ("cpp/CMakeLists.txt", "CMakeLists.txt",
        "scripts/run_original_grasu_finite.py", "tests/test_original_grasu_finite.py",
        "configs/experiments/original_grasu_finite_v1.json")]
    for directory in ("cpp/src", "cpp/include", "cpp/tests/original_grasu",
                      "spine_cycle_sim/experiments/grasu_finite",
                      "spine_cycle_sim/experiments/upstream_controls/grasu"):
        paths.extend(path for path in (root / directory).rglob("*") if path.suffix in (".cpp", ".hpp", ".py"))
    paths.extend(root / name for name in ("spine_cycle_sim/experiments/upstream_controls/execution.py",
                                        "spine_cycle_sim/experiments/campaign_runtime.py"))
    return [{"path": str(path.relative_to(root)), "sha256": sha256_file(path)} for path in sorted(set(paths))]


def prepare(directory: Path, case: int):
    directory.mkdir(parents=True, exist_ok=False)
    (directory / "initial.u32le").write_bytes(final_state(0))
    binary = array.array("Q", ((source(index) << 32) | (base(index) + 10) for index in range(SEGMENTS)))
    if binary.itemsize != 8:
        raise ValueError("G table requires 64-bit words")
    if sys.byteorder != "little":
        binary.byteswap()
    (directory / "binary.u64le").write_bytes(binary.tobytes())
    (directory / "rows.u64le").write_bytes(struct.pack("<QQ", HOT * 2 * 16,
        ((HOT * 2 * 16) << 32) | (SEGMENTS * 16)))
    changes = {}
    payload = bytearray(struct.pack("<I", len(batches(case))))
    for updates in batches(case):
        payload.extend(struct.pack("<I", len(updates)))
        payload.extend(struct.pack(f"<{len(updates)}Q", *(edge(item) for item in updates)))
        for segment, delta, deletion in updates:
            values = changes.setdefault(segment, {10, 40, 70})
            if deletion:
                if delta not in values:
                    raise ValueError("oracle absent deletion")
                values.remove(delta)
            else:
                if delta in values or len(values) >= 16:
                    raise ValueError("oracle invalid insertion")
                values.add(delta)
        payload.extend(struct.pack("<I", len(changes)))
        for segment, values in sorted(changes.items()):
            row = [base(segment) + delta for delta in sorted(values)] + [EMPTY] * (16 - len(values))
            payload.extend(struct.pack("<17I", segment, *row))
    (directory / "batches.bin").write_bytes(payload)
    return [{"path": str(path), "sha256": sha256_file(path), "bytes": path.stat().st_size}
            for path in sorted(directory.iterdir())]


def build_identity(binary):
    build = binary.parent.parent
    paths = [build / "CMakeCache.txt", build / "compile_commands.json"]
    paths.extend(build / "cpp/CMakeFiles" / target / "flags.make" for target in
                 ("spine_cycle_core.dir", "original_grasu_cycle.dir", "original_grasu_execution.dir"))
    if any(not path.is_file() for path in paths):
        raise ValueError("finite G requires exported CMake compiler/flag records")
    commands = json.loads((build / "compile_commands.json").read_text())
    selected = [row for row in commands if "original_grasu" in row["file"] or "/spine_cycle_core.dir/" in row["command"]]
    compiler = next(line.partition("=")[2] for line in (build / "CMakeCache.txt").read_text().splitlines()
                    if line.startswith("CMAKE_CXX_COMPILER:FILEPATH="))
    return {"binary": str(binary), "binary_sha256": sha256_file(binary),
        "compiler": compiler, "compiler_sha256": sha256_file(Path(compiler)),
        "compiler_version": subprocess.check_output([compiler, "--version"], text=True),
        "compile_commands": selected,
        "files": [{"path": str(path), "sha256": sha256_file(path)} for path in paths]}


def preserve(root, baseline):
    old = json.loads((baseline / "baseline.json").read_text())
    allowed = "cpp/CMakeLists.txt"
    changed = [row["path"] for row in old["files"] if sha256_file(root / row["path"]) != row["sha256"]]
    # Only the two independent build declarations may change an old file.
    before = old["build_preimages"][allowed]
    after = (root / allowed).read_text()
    library = after[after.index("add_library(original_grasu_cycle"):after.index("add_library(pma_adapter_cycle")]
    targets = after[after.index("  add_executable(original_grasu_execution"):after.index("  add_executable(pma_adapter_tests")]
    if changed != [allowed] or after.replace(library, "", 1).replace(targets, "", 1) != before:
        raise ValueError("finite G changed old source beyond independent build declarations")
    user = subprocess.check_output(["git", "diff", "--", "scripts/build_current_fpga_spine_v4_index.py"], cwd=root, text=True)
    if (user != old["user_dirty_diff"] or sha256_file(root / "build/sst/libspine_cycle.so") != old["plugin_sha256"] or
            sha256_file(root / "docs/experiments/comparisons/grasu_regraph_stage_validation/finite_pma_results.json") != old["accepted_A4_B_result_sha256"]):
        raise ValueError("finite G changed frozen evidence or user patch")
    return {"old_files": len(old["files"]), "changed_old_files": changed,
            "only_independent_build_declarations_changed": True,
            "production_plugin_preserved": True, "A4_B_result_preserved": True, "user_patch_preserved": True}
