"""Build one independent UBSan whole-path binary and repeat the declared inputs."""

from __future__ import annotations

from pathlib import Path

from spine_cycle_sim.experiments.campaign_runtime import atomic_write_json, sha256_file
from spine_cycle_sim.experiments.original_regraph_validation.analysis import same_typed
from spine_cycle_sim.experiments.upstream_controls.execution import dependency_identities
from .analysis import analyze


def verify_instrumented(root: Path, output: Path, compiler: str, contract: dict, report: dict, execute) -> dict:
    sources = [root / "cpp/src" / name for name in ("scheduler.cpp", "axi.cpp", "memory_backend.cpp")]
    sources.extend(sorted((root / "cpp/src/original_regraph").glob("*.cpp")))
    binary = output / "ubsan_a4"
    dependencies = output / "ubsan_dependencies.d"
    command = [compiler, "-std=c++20", "-O1", "-g0", "-Wall", "-Wextra", "-Wpedantic", "-Werror",
        "-fsanitize=undefined", "-fno-sanitize-recover=all", "-D_GLIBCXX_ASSERTIONS", "-MD", "-MT", "probe", "-MF", str(dependencies),
        f"-I{root / 'cpp/include'}", *map(str, sources),
        str(root / "cpp/tests/original_regraph/whole_graph/a4_execution.cpp"), "-o", str(binary)]
    execute("ubsan_compile", command, contract["build_timeout_seconds"])
    for name in contract["instrumented_cases"]:
        case = next(case for case in contract["cases"] if case["id"] == name)
        admitted = next(item for item in report["inputs"] if item["id"] == case["input"])
        directory = output / "ubsan" / name
        directory.mkdir(parents=True)
        step = execute(name + "_ubsan", [str(binary), admitted["directory"], str(directory), str(case["state_parents"]),
            str(case["latency"]), str(int(case["reverse"])), str(contract["max_cycles"])], contract["run_timeout_seconds"])
        result = analyze(Path(step["stdout"]).read_text(), directory, case, admitted, contract)
        reference = next(row for row in report["cases"] if row["id"] == name)["runs"][0]["analysis"]
        if Path(step["stderr"]).read_text() or not same_typed(result, reference):
            raise ValueError("UBSan changed full A4 state/cycles/ledgers or emitted diagnostics")
        atomic_write_json(directory / "analysis.json", result)
    return {"path": str(binary), "sha256": sha256_file(binary), "dependencies": dependency_identities(dependencies, root)}
