"""Run the same original-host matrix with independent undefined-behavior checks."""

from __future__ import annotations

from pathlib import Path

from spine_cycle_sim.experiments.campaign_runtime import atomic_write_json, sha256_file
from spine_cycle_sim.experiments.original_regraph_validation.analysis import same_typed
from spine_cycle_sim.experiments.upstream_controls.execution import dependency_identities
from .analysis import analyze_layout
from .preparation import compiler_command


def verify_instrumented(root: Path, output: Path, compiler: str, xrt_include: Path,
                        report: dict, contract: dict, execute) -> list[dict]:
    binaries = []
    for topology in contract["topologies"]:
        directory = output / topology["id"] / "ubsan"
        directory.mkdir()
        command = compiler_command(root, directory.parent / "prepared", topology, directory, compiler, xrt_include)
        command[1:1] = ["-fsanitize=undefined", "-fno-sanitize-recover=all", "-D_GLIBCXX_ASSERTIONS"]
        execute(topology["id"] + "_ubsan_compile", command, contract["compile_timeout_seconds"])
        binary = directory / "probe"
        binaries.append({"topology_id": topology["id"], "path": str(binary), "sha256": sha256_file(binary),
                         "dependencies": dependency_identities(directory / "dependencies.d", root)})
        for graph in report["inputs"]:
            case = next(row for row in report["cases"] if row["id"] == f"{topology['id']}_{graph['id']}")
            capture = directory / graph["id"]
            capture.mkdir()
            step = execute(case["id"] + "_ubsan", [str(binary), graph["path"], str(capture), str(contract["seed"]),
                str(topology["dense_partitions_argument"])], contract["run_timeout_seconds"])
            analysis = analyze_layout(Path(step["stdout"]).read_text(), capture, topology, graph, contract)
            if Path(step["stderr"]).read_text() or not same_typed(analysis, case["runs"][0]["analysis"]):
                raise ValueError("instrumentation changed original layout or emitted diagnostics")
            atomic_write_json(capture / "layout.json", analysis)
    return binaries
