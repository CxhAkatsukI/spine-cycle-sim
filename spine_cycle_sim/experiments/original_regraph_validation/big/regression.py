"""Compare old components and complete A4 graph executions exactly."""

import json
from pathlib import Path

from spine_cycle_sim.experiments.campaign_runtime import sha256_file
from spine_cycle_sim.experiments.original_regraph_execution.analysis import STATUS as A4_STATUS


def verify_legacy(root: Path, build: Path, output: Path, baseline: Path, contract: dict, execute) -> dict:
    frozen = json.loads((baseline / "baseline.json").read_text())
    for name, digest in frozen["source_hashes"].items():
        if name != "cpp/CMakeLists.txt" and sha256_file(root / name) != digest:
            raise ValueError("Big work changed existing Little/state/test source")
    checks = []
    for old in frozen["runs"]:
        step = execute("legacy_" + old["id"], [str(build / "cpp" / ("original_regraph_" + old["id"]))],
                       contract["run_timeout_seconds"])
        if old["exit_code"] != 0 or old["timed_out"] or any(
                Path(step[key]).read_bytes() != Path(old[key]).read_bytes() for key in ("stdout", "stderr")):
            raise ValueError("Big addition changed frozen Little/state values/cycles/counters")
        checks.append({"id": old["id"], "stdout_sha256": sha256_file(Path(step["stdout"])), "identical": True})
    previous = root / "results/upstream_stage_controls/a4_execution_final_v3"
    report = json.loads((previous / "report.json").read_text())
    if report["status"] != A4_STATUS:
        raise ValueError("whole A4 reference is not accepted")
    a4_contract = json.loads((previous / "contract.json").read_text())
    for case in a4_contract["cases"]:
        reference = next(row for row in report["cases"] if row["id"] == case["id"])["runs"][0]
        admitted = next(row for row in report["inputs"] if row["id"] == case["input"])
        directory = output / "legacy_a4" / case["id"]
        directory.mkdir(parents=True)
        step = execute("legacy_a4_" + case["id"], [str(build / "cpp/original_regraph_a4_execution"),
            admitted["directory"], str(directory), str(case["state_parents"]), str(case["latency"]),
            str(int(case["reverse"])), str(a4_contract["max_cycles"])], contract["run_timeout_seconds"])
        old_step = next(row for row in report["steps"] if row["id"] == case["id"] + "_first")
        if any(Path(step[key]).read_bytes() != Path(old_step[key]).read_bytes() for key in ("stdout", "stderr")):
            raise ValueError("Big addition changed whole A4 values/cycles/counters/lifecycles")
        hashes = []
        for index in range(4):
            path = directory / f"final_replica{index}.u32le"
            digest = sha256_file(path)
            if digest != sha256_file(Path(reference["directory"]) / path.name):
                raise ValueError("Big addition changed complete A4 state replica")
            hashes.append(digest)
        checks.append({"id": case["id"], "stdout_sha256": sha256_file(Path(step["stdout"])),
                       "replica_sha256": hashes, "identical": True})
    return {"checks": checks, "old_sources_unchanged_except_build_list": True,
            "whole_a4_reference_sha256": sha256_file(previous / "report.json"),
            "baseline_sha256": sha256_file(baseline / "baseline.json")}
