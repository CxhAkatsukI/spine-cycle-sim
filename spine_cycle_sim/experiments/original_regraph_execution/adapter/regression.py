"""Admit only the planned wiring extraction; compare every original A4 observation."""

import json
from pathlib import Path
import subprocess

from spine_cycle_sim.experiments.campaign_runtime import atomic_write_json, sha256_file
from ..analysis import analyze
from ..instrumentation import verify_instrumented


def preserve(root: Path, baseline: Path):
    record = json.loads((baseline / "baseline.json").read_text())
    if record["status"] != "ALL_EIGHT_A4_CURRENT_EXECUTIONS_IDENTICAL_TO_FROZEN_RESULTS": raise ValueError("adapter requires completed pre-edit A4 baseline")
    changed = [item["path"] for item in record["files"] if sha256_file(root / item["path"]) != item["sha256"]]
    if changed != ["cpp/tests/original_regraph/whole_graph/wiring.hpp"]: raise ValueError("adapter changed undeclared old source/evidence: " + str(changed))
    user = subprocess.check_output(["git", "diff", "--", "scripts/build_current_fpga_spine_v4_index.py"], cwd=root, text=True)
    same_worktree = Path(record["binary"]["path"]).is_relative_to(root)
    if same_worktree and user != record["dirty_diff"]: raise ValueError("adapter changed original user patch")
    return {"baseline_sha256": sha256_file(baseline / "baseline.json"), "old_files": len(record["files"]),
        "declared_extraction_only": changed, "user_patch_preserved": True if same_worktree else None}


def run(root: Path, baseline: Path, output: Path, inputs: list, compiler: str, execute):
    previous = json.loads((baseline / "baseline.json").read_text()); contract = previous["contract"]
    build = output / "build"
    execute("configure", ["cmake", "-S", str(root), "-B", str(build), "-DCMAKE_BUILD_TYPE=Release", "-DCMAKE_EXPORT_COMPILE_COMMANDS=ON", f"-DCMAKE_CXX_COMPILER={compiler}"], 600)
    execute("build", ["cmake", "--build", str(build), "-j2"], 600)
    execute("ctest", ["ctest", "--test-dir", str(build), "--output-on-failure"], 300)
    binary = build / "cpp/original_regraph_a4_execution"; cases = []
    for case, old in zip(contract["cases"], previous["cases"], strict=True):
        admitted = next(row for row in inputs if row["id"] == case["input"])
        directory = output / "a4" / case["id"]; directory.mkdir(parents=True)
        step = execute("a4_" + case["id"], [str(binary), admitted["directory"], str(directory), str(case["state_parents"]), str(case["latency"]), str(int(case["reverse"])), str(contract["max_cycles"])], 300)
        value = analyze(Path(step["stdout"]).read_text(), directory, case, admitted, contract)
        if value != old["analysis"] or Path(step["stderr"]).read_text() or Path(step["stdout"]).read_text() != old["stdout"]: raise ValueError("shared wiring changed A4 full observations")
        cases.append({"id": case["id"], "runs": [{"directory": str(directory), "analysis": value}]})
    subreport = {"inputs": inputs, "cases": cases}
    instrumented = verify_instrumented(root, output, compiler, contract, subreport, execute)
    record = {"cases": cases, "all_eight_full_observations_identical": True, "ubsan_three_inputs_identical": True,
        "binaries": [{"path": str(binary), "sha256": sha256_file(binary)}, instrumented], "preservation": preserve(root, baseline)}
    atomic_write_json(output / "wiring_regression.json", record); return record
