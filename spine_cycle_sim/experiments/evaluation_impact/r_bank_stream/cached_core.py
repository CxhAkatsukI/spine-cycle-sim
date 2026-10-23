"""Reuse a checked core without changing it; compile only the experiment entry points."""

import json
from pathlib import Path
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
    if source not in ("convergence", "credit_control_test", "adapter_floor",
                      "prefetch_compact", "prefetch_compact_test"):
        raise ValueError("only approved experiment entry points may be compiled")
    return [str(compiler), "-O3", "-DNDEBUG", "-std=gnu++20", "-Wall", "-Wextra", "-Wpedantic", "-Werror",
            "-I" + str(root / "cpp/include"), str(root / ("cpp/tests/evaluation_impact/" + source + ".cpp")),
            "-o", str(output), str(core / "liboriginal_regraph_cycle.a"), str(core / "libspine_cycle_core.a")]


def validate_convergence(root, reference, compiler, *, complete_status="PREFETCH_CAPACITY_COMPLETE_SIMULATOR_PREDICTION"):
    """Reuse only unchanged numerical code from a complete, tested capacity run."""
    report = json.loads(reference.read_text())
    if complete_status not in ("PREFETCH_CAPACITY_COMPLETE_SIMULATOR_PREDICTION",
                              "GATHER_REUSE_COMPLETE_SIMULATOR_PREDICTION"):
        raise ValueError("unknown complete-core reference type")
    if (report.get("status") != complete_status or
            report.get("pins_unchanged") is not True or len(report.get("r_rows", [])) != 12 or
            report.get("failures") != []):
        raise ValueError("complete tested capacity reference required for core reuse")
    pins = {Path(row["path"]): row for row in report["pins"]}
    sources = {p for owner in ("cpp/src", "cpp/include") for p in (root / owner).rglob("*")
               if p.is_file()} | {root / name for name in ("CMakeLists.txt", "cpp/CMakeLists.txt")}
    if not sources <= pins.keys():
        raise ValueError("capacity snapshot omits current core source files")
    libraries = [p for p in pins if p.name == "libspine_cycle_core.a"]
    if len(libraries) != 1:
        raise ValueError("one checked numerical library required")
    core = libraries[0].parent
    required = sources | {compiler.resolve(), core / "libspine_cycle_core.a",
        core / "liboriginal_regraph_cycle.a", core.parent.parent / "CMakeCache.txt",
        core.parent.parent / "compile_commands.json"}
    inputs = reference.parent / "inputs/warm_update"
    required.update(p for p in inputs.iterdir() if p.is_file())
    if not required <= pins.keys() or any(
            sha256_file(p) != pins[p]["sha256"] for p in required):
        raise ValueError("cached numerical source, input, compiler or library differs")
    evidence = []
    for name in ("build_core", "core_ctest"):
        matches = [step for step in report["steps"]
                   if Path(step["stdout"]).name == name + ".stdout.txt"]
        if len(matches) != 1 or matches[0]["exit_code"] or matches[0]["timed_out"]:
            raise ValueError("complete passing core build/test evidence required")
        stdout = Path(matches[0]["stdout"])
        if name == "core_ctest" and "100% tests passed, 0 tests failed out of 37" not in stdout.read_text():
            raise ValueError("all 37 core tests required")
        evidence.append(pin(stdout))
    return core, [pin(reference), *[pins[p] for p in sorted(required)], *evidence]
