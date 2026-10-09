"""Verify default-preserving AXI helper changes against frozen executable outputs."""

from __future__ import annotations

import json
from pathlib import Path

from spine_cycle_sim.experiments.campaign_runtime import sha256_file
from spine_cycle_sim.experiments.original_regraph_validation.analysis import admit_captures
from spine_cycle_sim.experiments.original_regraph_validation.state_sources import admit_apply


def verify_legacy(root: Path, build: Path, baseline: Path, contract: dict, execute,
                  gather_captures: Path | None = None, apply_captures: Path | None = None) -> dict:
    frozen = json.loads((baseline / "baseline.json").read_text())
    if [row["target"] for row in frozen["runs"]] != ["gather_tests", "frontend_tests", "state_tests", "iteration_tests"]:
        raise ValueError("legacy baseline does not cover the fixed four component gates")
    results = []
    for row in frozen["runs"]:
        if row["exit_code"] != 0 or row["timed_out"]:
            raise ValueError("legacy baseline contains an unsuccessful run")
        observed = execute("legacy_" + row["target"], [str(build / "cpp" / ("original_regraph_" + row["target"]))],
                           contract["run_timeout_seconds"])
        if (Path(row["stdout"]).read_bytes() != Path(observed["stdout"]).read_bytes() or
                Path(row["stderr"]).read_bytes() != Path(observed["stderr"]).read_bytes()):
            raise ValueError("default AXI helper changed frozen component values/cycles/counters")
        results.append({"target": row["target"], "stdout_sha256": sha256_file(Path(row["stdout"])), "identical": True})
    folder = root / "docs/experiments/comparisons/grasu_regraph_stage_validation"
    old_binary_root = Path(frozen["runs"][0]["command"][0]).parent
    for name, evidence_name in (("source_comparison", "finite_gather_results.json"),
                               ("state_comparison", "state_results.json")):
        captures = json.loads((folder / evidence_name).read_text())["source_captures"]
        reference_hashes = [item["sha256"] for item in captures]
        if name == "source_comparison" and gather_captures is not None:
            source_contract = json.loads((root / "configs/experiments/original_regraph_gather_validation_v1.json").read_text())
            captures = admit_captures(gather_captures, root, source_contract)
        if name == "state_comparison" and apply_captures is not None:
            source_contract = json.loads((root / "configs/experiments/original_regraph_state_validation_v1.json").read_text())
            captures = admit_apply(apply_captures, root, source_contract)
        if [item["sha256"] for item in captures] != reference_hashes:
            raise ValueError("regenerated original-source values differ from frozen references")
        if any(sha256_file(Path(item["path"])) != item["sha256"] for item in captures):
            raise ValueError("legacy original-source capture changed")
        arguments = [item["path"] for item in captures]
        old = execute("old_" + name, [str(old_binary_root / ("original_regraph_" + name)), *arguments],
                      contract["run_timeout_seconds"])
        new = execute("legacy_" + name, [str(build / "cpp" / ("original_regraph_" + name)), *arguments],
                      contract["run_timeout_seconds"])
        if (Path(old["stdout"]).read_bytes() != Path(new["stdout"]).read_bytes() or
                Path(old["stderr"]).read_bytes() != Path(new["stderr"]).read_bytes()):
            raise ValueError("default helper changed complete original-source comparisons")
        results.append({"target": name, "stdout_sha256": sha256_file(Path(new["stdout"])),
                        "identical": True, "original_captures": captures})
    return {"baseline_sha256": sha256_file(baseline / "baseline.json"), "results": results,
            "default_component_and_full_source_comparison_outputs_identical": True}
