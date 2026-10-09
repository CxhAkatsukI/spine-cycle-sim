"""Reuse admitted original-host tasks and preserve every logical edge."""

import json
from pathlib import Path
import subprocess

from spine_cycle_sim.experiments.campaign_runtime import sha256_file
from ..original_regraph_execution.preparation import admit_inputs, verify_inputs
from ..original_regraph_execution.adapter.preparation import prepare
from ..original_regraph_execution.adapter.analysis import inspect

DECLARED_OLD_CHANGES = ["cpp/CMakeLists.txt", "cpp/tests/original_regraph/whole_graph/a4_execution.cpp",
                        "cpp/tests/original_regraph/whole_graph/compute_wiring.hpp"]


def preserve(root: Path, baseline: Path):
    record = json.loads((baseline / "baseline.json").read_text())
    if record["status"] != "ALL_EIGHT_A4_IDENTICAL_TO_ACCEPTED":
        raise ValueError("finite PMA requires the completed pre-edit full A4 baseline")
    changed = [item["path"] for item in record["files"] if sha256_file(root / item["path"]) != item["sha256"]]
    if sorted(changed) != DECLARED_OLD_CHANGES:
        raise ValueError("finite PMA changed undeclared old source: " + str(changed))
    user = subprocess.check_output(["git", "diff", "--", "scripts/build_current_fpga_spine_v4_index.py"], cwd=root, text=True)
    if Path(record["binary"]["path"]).is_relative_to(root) and user != record["user_dirty_diff"]:
        raise ValueError("finite PMA changed preexisting user patch")
    return {"baseline_sha256": sha256_file(baseline / "baseline.json"), "old_files": len(record["files"]),
            "declared_old_changes": changed, "same_worktree_user_patch_preserved": user == record["user_dirty_diff"]}


def inputs(root: Path, source_run: Path, baseline: Path, output: Path):
    previous = json.loads((baseline / "baseline.json").read_text())
    admitted = admit_inputs(root, source_run, output)
    for item, old in zip(admitted, previous["inputs"], strict=True):
        item["adapter_layout"] = prepare(Path(item["directory"]))
        facts, controls = inspect(Path(item["directory"]))
        if (item["id"] != old["id"] or item["descriptor_sha256"] != old["descriptor_sha256"] or
                item["layout"] != old["layout"] or item["adapter_layout"] != old["adapter_layout"]):
            raise ValueError("finite PMA input/task/PMA identity differs from frozen source control")
        item["source_counts"] = facts
        item["compatibility_controls"] = controls
    verify_inputs(admitted)
    return admitted
