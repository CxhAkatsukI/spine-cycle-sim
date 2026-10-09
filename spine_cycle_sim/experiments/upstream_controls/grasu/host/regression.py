"""Fresh-build every earlier G source fixture and compare complete frozen analyses."""

import json
from pathlib import Path

from spine_cycle_sim.experiments.campaign_runtime import sha256_file
from spine_cycle_sim.experiments.upstream_controls.execution import dependency_identities
from ..analysis import analyze
from ..preparation import compiler_command, identities


def run(root: Path, source: Path, include: Path, compiler: str, output: Path, execute):
    folder = root / "docs/experiments/comparisons/grasu_regraph_stage_validation"
    record = json.loads((folder / "grasu_source_path_results.json").read_text())
    if record["source_identities"] != identities(root): raise ValueError("G new host work changed previous source control")
    directory = output / "legacy"; directory.mkdir()
    execute("legacy_compile", compiler_command(root, source, include, directory, compiler), compile=True)
    binary = directory / "probe"; results = []
    for case, row in enumerate(record["cases"]):
        target = directory / row["id"]; target.mkdir()
        step = execute("legacy_" + row["id"], [str(binary), str(case), str(target / "protocol.u32le"), str(target / "state.u32le")])
        result = analyze(target, case, Path(step["stdout"]), Path(step["stderr"]))
        if result != row["runs"][0]["analysis"]: raise ValueError("G host work changed previous complete state/protocol/counters")
        results.append({"id": row["id"], "analysis": result, "identical": True, "directory": str(target)})
    return {"previous_results_sha256": sha256_file(folder / "grasu_source_path_results.json"), "cases": results,
        "binary": {"path": str(binary), "sha256": sha256_file(binary), "dependencies": dependency_identities(directory / "dependencies.d", root)}}
