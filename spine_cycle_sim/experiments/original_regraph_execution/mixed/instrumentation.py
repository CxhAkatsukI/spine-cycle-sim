"""Independent sanitizer build and complete graph-state repeat."""

from pathlib import Path

from spine_cycle_sim.experiments.campaign_runtime import sha256_file
from spine_cycle_sim.experiments.original_regraph_validation.analysis import same_typed
from spine_cycle_sim.experiments.upstream_controls.execution import dependency_identities
from .analysis import analyze


def verify(root: Path, output: Path, compiler: str, contract: dict, report: dict, execute) -> dict:
    sources = [root / "cpp/src" / name for name in ("scheduler.cpp", "axi.cpp", "memory_backend.cpp")]
    sources.extend(sorted((root / "cpp/src/original_regraph").glob("*.cpp")))
    binary = output / "ubsan_mixed"; dependencies = output / "ubsan_dependencies.d"
    command = [compiler, "-std=c++20", "-O1", "-g0", "-Wall", "-Wextra", "-Wpedantic", "-Werror",
        "-fsanitize=undefined", "-fno-sanitize-recover=all", "-D_GLIBCXX_ASSERTIONS", "-MD", "-MT", "probe", "-MF", str(dependencies),
        f"-I{root / 'cpp/include'}", *map(str, sources), str(root / "cpp/tests/original_regraph/whole_graph/mixed/execution.cpp"), "-o", str(binary)]
    execute("ubsan_compile", command, contract["build_timeout_seconds"])
    for name in contract["instrumented_cases"]:
        case = next(item for item in contract["cases"] if item["id"] == name)
        admitted = next(item for item in report["inputs"] if item["id"] == case["input"])
        directory = output / "ubsan" / name; directory.mkdir(parents=True)
        step = execute(name + "_ubsan", [str(binary), admitted["directory"], str(directory), str(case["state_parents"]),
            str(case["latency"]), str(int(case["reverse"])), str(contract["max_cycles"]), "1"], contract["run_timeout_seconds"])
        expected = next(item for item in report["cases"] if item["id"] == name)["runs"][0]["analysis"]
        if Path(step["stderr"]).read_text() or not same_typed(analyze(Path(step["stdout"]).read_text(), directory, case, admitted, contract), expected):
            raise ValueError("mixed UBSan changed full state/timing/ledgers or emitted diagnostics")
    return {"path": str(binary), "sha256": sha256_file(binary), "dependencies": dependency_identities(dependencies, root)}
