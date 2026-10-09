"""Exact pre-edit component/A4 controls, with hash-verified archived references."""

import hashlib
import json
from pathlib import Path
import tarfile

from spine_cycle_sim.experiments.campaign_runtime import sha256_file
from spine_cycle_sim.experiments.original_regraph_validation.analysis import same_typed
from ..preparation import admit_inputs, verify_inputs
from ..analysis import analyze as analyze_a4

BUILD_EXTENSIONS = {"cpp/CMakeLists.txt", "cpp/include/spine_sim/original_regraph/big_merge.hpp",
                    "cpp/src/original_regraph/big_merge.cpp"}


def archived(folder: Path, stem: str, digest: str) -> bytes:
    record = json.loads((folder / (stem + "_verification.json")).read_text())
    archive = folder / {"a4": "raw_a4_graph_execution.tar.gz", "big_gather": "raw_big_gather.tar.gz",
                        "big_frontend": "raw_big_frontend.tar.gz"}[stem]
    if sha256_file(archive) != record["archive_sha256"]: raise ValueError("frozen regression archive changed")
    item = next((item for item in record["files"] if item["sha256"] == digest), None)
    if item is None or not 0 <= item["bytes"] <= 100 * 1024**2: raise ValueError("regression reference absent or excessive")
    with tarfile.open(archive, "r:gz") as bundle:
        members = [member for member in bundle.getmembers() if member.name == item["path"]]
        if len(members) != 1 or not members[0].isfile() or members[0].size != item["bytes"]:
            raise ValueError("regression archive member type/extent/uniqueness changed")
        with bundle.extractfile(members[0]) as stream: payload = stream.read()
    if hashlib.sha256(payload).hexdigest() != digest: raise ValueError("regression archive payload changed")
    return payload


def verify(root: Path, build: Path, output: Path, baseline: Path, input_run: Path, contract: dict, execute) -> dict:
    frozen = json.loads((baseline / "baseline.json").read_text())
    changed = [name for name, digest in frozen["source_hashes"].items() if sha256_file(root / name) != digest]
    if set(changed) != BUILD_EXTENSIONS: raise ValueError("mixed work changed undeclared old implementation paths")
    checks = []
    names = ["gather_tests", "frontend_tests", "state_tests", "iteration_tests", "big_tests", "big_frontend_tests"]
    if [row["id"] for row in frozen["runs"]] != names: raise ValueError("mixed pre-edit baseline coverage incomplete")
    for old in frozen["runs"]:
        name = old["id"]
        row = execute("legacy_" + name, [str(build / "cpp" / ("original_regraph_" + name))], contract["run_timeout_seconds"])
        if old["exit_code"] or old["timed_out"] or any(Path(row[key]).read_bytes() != (baseline / Path(old[key]).name).read_bytes()
                for key in ("stdout", "stderr")): raise ValueError("mixed extension changed old component output")
        checks.append({"id": name, "stdout_sha256": sha256_file(Path(row["stdout"])), "identical": True})
    folder = root / "docs/experiments/comparisons/grasu_regraph_stage_validation"
    old_a4 = json.loads((folder / "a4_results.json").read_text())
    a4_contract = json.loads(archived(folder, "a4", old_a4["contract_sha256"]))
    inputs = admit_inputs(root, input_run, output / "legacy_a4_inputs")
    for case in a4_contract["cases"]:
        reference = next(row for row in old_a4["cases"] if row["id"] == case["id"])["runs"][0]["analysis"]
        admitted = next(item for item in inputs if item["id"] == case["input"])
        directory = output / "legacy_a4" / case["id"]; directory.mkdir(parents=True)
        step = execute("legacy_a4_" + case["id"], [str(build / "cpp/original_regraph_a4_execution"), admitted["directory"],
            str(directory), str(case["state_parents"]), str(case["latency"]), str(int(case["reverse"])), str(a4_contract["max_cycles"])],
            contract["run_timeout_seconds"])
        result = analyze_a4(Path(step["stdout"]).read_text(), directory, case, admitted, a4_contract)
        if not same_typed(result, reference) or Path(step["stderr"]).read_text(): raise ValueError("mixed addition changed whole A4 state/cycles/ledgers")
        checks.append({"id": case["id"], "identical": True, "analysis": result})
    for stem, target, step_id in (("big_gather", "big_comparison", "big_comparison_first"),
                                  ("big_frontend", "big_frontend_comparison", "big_frontend_comparison_first")):
        old = json.loads((folder / (stem + "_results.json")).read_text())
        capture = output / ("legacy_" + stem + ".u32le")
        with capture.open("xb") as stream: stream.write(archived(folder, stem, old["source_control"]["capture"]["sha256"]))
        step = execute("legacy_" + target, [str(build / "cpp" / ("original_regraph_" + target)), str(capture)], contract["run_timeout_seconds"])
        reference = next(row for row in old["steps"] if row["id"] == step_id)
        # The archive index, rather than historical absolute run paths, owns the reference.
        index = json.loads((folder / (stem + "_verification.json")).read_text())["files"]
        for key, suffix in (("stdout", ".stdout.txt"), ("stderr", ".stderr.txt")):
            item = next(item for item in index if item["path"].endswith("/" + step_id + suffix))
            if Path(step[key]).read_bytes() != archived(folder, stem, item["sha256"]): raise ValueError("mixed addition changed complete Big source comparison")
        checks.append({"id": target, "identical": True, "capture_sha256": sha256_file(capture), "old_exit_code": reference["exit_code"],
                       "stdout_sha256": sha256_file(Path(step["stdout"])), "stderr_sha256": sha256_file(Path(step["stderr"]))})
    return {"checks": checks, "inputs": inputs, "declared_changed_paths": sorted(changed),
        "baseline_sha256": sha256_file(baseline / "baseline.json"), "legacy_reference_paths_relocated": True}


def recheck(root: Path, run: Path, report: dict) -> None:
    baseline = Path(report["legacy_baseline"])
    frozen = json.loads((baseline / "baseline.json").read_text())
    if sha256_file(baseline / "baseline.json") != report["legacy"]["baseline_sha256"]: raise ValueError("mixed baseline changed")
    steps = {item["id"]: item for item in report["steps"]}
    checks = report["legacy"]["checks"]
    for old in frozen["runs"]:
        step = steps["legacy_" + old["id"]]
        check = next(item for item in checks if item["id"] == old["id"])
        if sha256_file(Path(step["stdout"])) != check["stdout_sha256"] or any(
                Path(step[key]).read_bytes() != (baseline / Path(old[key]).name).read_bytes() for key in ("stdout", "stderr")):
            raise ValueError("mixed pre-edit component raw regression changed")
    folder = root / "docs/experiments/comparisons/grasu_regraph_stage_validation"
    old_a4 = json.loads((folder / "a4_results.json").read_text())
    contract = json.loads(archived(folder, "a4", old_a4["contract_sha256"]))
    verify_inputs(report["legacy"]["inputs"])
    for case in contract["cases"]:
        step = steps["legacy_a4_" + case["id"]]
        admitted = next(item for item in report["legacy"]["inputs"] if item["id"] == case["input"])
        actual = analyze_a4(Path(step["stdout"]).read_text(), run / "legacy_a4" / case["id"], case, admitted, contract)
        reference = next(item for item in old_a4["cases"] if item["id"] == case["id"])["runs"][0]["analysis"]
        if not same_typed(actual, reference) or Path(step["stderr"]).read_text(): raise ValueError("mixed full A4 raw regression changed")
    for target, stem in (("big_comparison", "big_gather"), ("big_frontend_comparison", "big_frontend")):
        step = steps["legacy_" + target]
        check = next(item for item in checks if item["id"] == target)
        if (check["old_exit_code"] != 0 or sha256_file(run / ("legacy_" + stem + ".u32le")) != check["capture_sha256"] or
                any(sha256_file(Path(step[key])) != check[key + "_sha256"] for key in ("stdout", "stderr"))):
            raise ValueError("mixed complete Big source raw regression changed")
