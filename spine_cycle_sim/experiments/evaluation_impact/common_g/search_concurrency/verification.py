"""Index fresh regressions without promoting a failed performance gate."""

import argparse
from collections import Counter
import json
from pathlib import Path
import re
import tarfile

from spine_cycle_sim.experiments.campaign_runtime import atomic_write_json, sha256_file
from ..study import ROOT


def historical_identity(previous):
    old_path = previous / "python-verification-v2/historical.json"
    old = json.loads(old_path.read_text())
    if old["status"] != "HISTORICAL_IDENTITY_FAILURES_RETAINED" or \
            old["identity_drift"]["current_mismatched_subassertions"] != 27:
        raise ValueError("complete preceding historical failure audit required")
    refactor = json.loads((ROOT / "docs/repository/sst_spine_refactor/spine_equivalence.json").read_text())
    rows = [row for row in refactor["candidate_identity"]["source"]["files"]
        if row["path"].startswith(("cpp/src/", "cpp/include/", "cpp/sst/")) and
        row["path"].endswith((".cpp", ".hpp"))]
    rows += json.loads((ROOT / "docs/experiments/comparisons/grasu_regraph_stage_validation/finite_grasu_results.json").read_text())["model"]["files"]
    current = [row["path"] for row in rows if sha256_file(ROOT / row["path"]) != row["sha256"]]
    before = old["identity_drift"]["mismatched_paths_with_repetitions"]
    added = ["cpp/include/spine_sim/original_grasu/types.hpp",
             "cpp/src/original_grasu/hot_store.cpp", "cpp/tests/original_grasu/system.hpp"]
    if Counter(current) - Counter(before) != Counter(added) or Counter(before) - Counter(current):
        raise ValueError("undeclared historical source identity changes")
    return {"previous_mismatched_subassertions": 27, "current_mismatched_subassertions": len(current),
        "mismatched_paths_with_repetitions": current, "newly_changed_paths": added,
        "reason": "default-off reference forwarding and explicit timing injection; 190 old observations replay exactly",
        "previous_audit": {"path": str(old_path), "sha256": sha256_file(old_path)},
        "frozen_manifests_rewritten": False, "suite_reported_green": False}


def package(base, previous, output):
    sources, checks = {}, []

    def include(path):
        sources[str(path.relative_to(base))] = path

    def report(name, status, steps):
        path = base / name
        value = json.loads(path.read_text())
        if value["status"] != status or len(value["steps"]) != steps:
            raise ValueError("incomplete regression: " + name)
        include(path)
        return value

    def check(step, code, label):
        if step["exit_code"] != code or step["timed_out"]:
            raise ValueError("unexpected regression outcome: " + label)
        checks.append({"name": label, "expected_exit_code": code, **step})
        for kind in ("stdout", "stderr"):
            include(Path(step[kind]))
        resources = Path(step["stdout"].replace(".stdout.txt", ".resources.json"))
        if json.loads(resources.read_text()) != step:
            raise ValueError("step resource record changed: " + label)
        include(resources)

    core = report("core-verification.json", "FRESH_CORE_REGRESSIONS_PASS", 3)
    sst = report("sst-verification/results.json", "DEFAULT_SST_SMOKES_PASS_NOT_CANDIDATE_TIMING", 3)
    focused = report("python-verification/results.json", "FOCUSED_PASS", 1)
    for label, group in (("core", core), ("default-sst", sst), ("python", focused)):
        for index, step in enumerate(group["steps"]):
            check(step, 0, f"{label}/{index}")
    sst_build = base / "sst-verification/build.json"
    include(sst_build)
    check(json.loads(sst_build.read_text()), 0, "fresh-sst-build")
    if "100% tests passed, 0 tests failed out of 31" not in \
            Path(core["steps"][-1]["stdout"]).read_text():
        raise ValueError("complete 31-target core regression required")
    summary = re.findall(r"^Ran (\d+) tests? in ",
                         Path(focused["steps"][0]["stderr"]).read_text(), re.MULTILINE)
    if len(summary) != 1 or int(summary[0]) != focused["tests_run"]:
        raise ValueError("focused Python test count differs from saved execution")
    historical_path = base / "python-verification/historical.json"
    historical = json.loads(historical_path.read_text())
    include(historical_path)
    if historical["status"] != "HISTORICAL_IDENTITY_FAILURES_RETAINED" or \
            historical["identity_drift"] != historical_identity(previous):
        raise ValueError("historical failure set changed")
    check(historical["step"], 1, "retained-historical-identities")
    audit_attempt = base / "python-verification/historical-audit-attempt.json"
    if audit_attempt.is_file():
        include(audit_attempt)
    for attempt in sorted((base / "python-verification").glob("focused-attempt-*.json")):
        value = json.loads(attempt.read_text())
        if value["status"] not in ("FOCUSED_PASS", "FAILED_RETAINED") or len(value["steps"]) != 1:
            raise ValueError("incomplete retained Python attempt")
        include(attempt)
        code = 0 if value["status"] == "FOCUSED_PASS" else 1
        check(value["steps"][0], code, "retained-" + attempt.stem)
    sst_exact = []
    for name in ("memory/summary.json", "native/result.json"):
        path, old = base / "sst-verification" / name, previous / "sst-verification" / name
        if json.loads(path.read_text()) != json.loads(old.read_text()):
            raise ValueError("default SST behavior changed: " + name)
        include(path)
        sst_exact.append({"file": name, "previous": str(old), "previous_sha256": sha256_file(old)})
    for name in ("freeze/manifest.json", "core/CMakeCache.txt", "core/compile_commands.json"):
        include(base / name)
    output.mkdir(parents=True, exist_ok=False)
    archive, members = output / "regressions.tar.gz", []
    with tarfile.open(archive, "w:gz") as handle:
        for name, path in sorted(sources.items()):
            handle.add(path, arcname=name, recursive=False)
            members.append({"member": name, "source": str(path),
                            "sha256": sha256_file(path), "bytes": path.stat().st_size})
    identities = []
    for name in ("freeze/sources.tar.gz", "core/cpp/libspine_cycle_core.a",
            "core/cpp/liboriginal_grasu_cycle.a", "sst/libspine_cycle.so",
            "matrix/build/common_g_execution"):
        path = base / name
        identities.append({"path": str(path), "sha256": sha256_file(path), "bytes": path.stat().st_size})
    result = {"status": "REGRESSIONS_PASS_PERFORMANCE_REFERENCE_AND_HARDWARE_GATES_OPEN",
        "archive": {"file": archive.name, "sha256": sha256_file(archive), "bytes": archive.stat().st_size},
        "members": members, "checks": checks, "machine_local_identities": identities,
        "core_tests": 31, "focused_python_tests": focused["tests_run"],
        "sst_exact_default_smokes": sst_exact, "historical_identity": historical["identity_drift"],
        "baseline_admitted": False, "hardware_timing_admitted": False,
        "publication_match_admitted": False, "candidate_sst_timing_admitted": False,
        "new_spine_comparison_executed": False}
    atomic_write_json(output / "index.json", result)
    return result


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    for key in ("base", "previous", "output"):
        parser.add_argument("--" + key, type=Path, required=True)
    args = parser.parse_args()
    result = package(args.base, args.previous, args.output)
    print(json.dumps({"status": result["status"], "core_tests": result["core_tests"]}))
