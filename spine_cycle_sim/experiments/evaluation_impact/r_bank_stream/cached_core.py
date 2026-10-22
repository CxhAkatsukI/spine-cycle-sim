"""Reuse a checked core without changing it; compile only the experiment entry points."""

import json
from spine_cycle_sim.experiments.campaign_runtime import sha256_file
from ..r_credits.freeze import pin


def validate(root, gates):
    summary = json.loads((gates / "summary.json").read_text())
    snapshot = json.loads((gates / "source_before.json").read_text())
    if summary.get("status") != "PASS" or summary.get("source_unchanged") is not True:
        raise ValueError("cached core must have passed its build and regression campaign")
    rows = [row for row in snapshot["files"]
            if row["path"].startswith(("cpp/src/", "cpp/include/")) or row["path"] in
            ("CMakeLists.txt", "cpp/CMakeLists.txt")]
    expected = {str(p.relative_to(root)) for owner in ("cpp/src", "cpp/include")
                for p in (root / owner).rglob("*") if p.is_file()}
    expected.update(("CMakeLists.txt", "cpp/CMakeLists.txt"))
    if not expected <= {row["path"] for row in rows}:
        raise ValueError("cached snapshot omits current core source files")
    if any(sha256_file(root / row["path"]) != row["sha256"] for row in rows):
        raise ValueError("cached core differs from current numerical source")
    for name in ("core_build", "core_ctest"):
        attempts = [row["resources"] for row in summary["attempts"] if row["name"] == name]
        if len(attempts) != 1 or attempts[0]["exit_code"] or attempts[0]["timed_out"]:
            raise ValueError("cached core has no passing complete build/test evidence")
    core = gates / "core/cpp"
    paths = [gates / "summary.json", gates / "source_before.json", gates / "source_archive.json",
             gates / "core/CMakeCache.txt", core / "liboriginal_regraph_cycle.a", core / "libspine_cycle_core.a"]
    return core, [pin(p) for p in paths]


def command(root, core, output, compiler, source):
    if source not in ("convergence", "credit_control_test"):
        raise ValueError("only the two experiment entry points may be compiled")
    return [str(compiler), "-O3", "-DNDEBUG", "-std=gnu++20", "-Wall", "-Wextra", "-Wpedantic", "-Werror",
            "-I" + str(root / "cpp/include"), str(root / ("cpp/tests/evaluation_impact/" + source + ".cpp")),
            "-o", str(output), str(core / "liboriginal_regraph_cycle.a"), str(core / "libspine_cycle_core.a")]
