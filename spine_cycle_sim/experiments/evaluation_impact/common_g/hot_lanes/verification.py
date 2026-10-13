"""Index completed regression logs and preserve historical identity failures."""

import argparse
import hashlib
import json
from pathlib import Path
import shutil
import subprocess

from spine_cycle_sim.experiments.campaign_runtime import atomic_write_json, sha256_file
from ..study import ROOT


def historical_drift():
    study = ROOT / "docs/experiments/comparisons/grasu_regraph_stage_validation"
    refactor = json.loads((ROOT / "docs/repository/sst_spine_refactor/spine_equivalence.json").read_text())
    identities = [row for row in refactor["candidate_identity"]["source"]["files"]
        if row["path"].startswith(("cpp/src/", "cpp/include/", "cpp/sst/")) and
        row["path"].endswith((".cpp", ".hpp"))]
    identities += json.loads((study / "finite_grasu_results.json").read_text())["model"]["files"]
    current, before = [], []
    for row in identities:
        source = subprocess.check_output(["git", "show", "d510ea3:" + row["path"]], cwd=ROOT)
        if hashlib.sha256(source).hexdigest() != row["sha256"]:
            before.append(row["path"])
        if sha256_file(ROOT / row["path"]) != row["sha256"]:
            current.append(row["path"])
    if current != before:
        raise ValueError("historical mismatch set changed; inspect before delivery")
    return {"already_mismatched_subassertions_at_d510ea3": len(before),
        "current_mismatched_subassertions": len(current),
        "mismatched_paths_with_repetitions": current,
        "frozen_manifests_rewritten": False, "suite_reported_green": False}


def package(base, output):
    output.mkdir(parents=True, exist_ok=False)
    checks, files = [], []
    for name, expected in (("verification", (0, 0)), ("sst-verification", (0, 0, 0)),
                           ("python-verification", (0, 1))):
        path = base / name / "results.json"
        report = json.loads(path.read_text())
        if report["status"] not in ("CORE_AND_SST_BUILD_PASS",
                "DEFAULT_SST_SMOKES_PASS_NOT_CANDIDATE_TIMING",
                "FOCUSED_PASS_HISTORICAL_IDENTITY_REVIEW_REQUIRED") or \
                len(report["steps"]) != len(expected):
            raise ValueError("incomplete verification: " + name)
        files.append((name + ".json", path))
        for index, (step, exit_code) in enumerate(zip(report["steps"], expected)):
            if step["exit_code"] != exit_code or step["timed_out"]:
                raise ValueError("unexpected verification outcome: " + name)
            checks.append({"name": f"{name}/{index}", "expected_exit_code": exit_code, **step})
            for kind in ("stdout", "stderr"):
                files.append((f"{name}/{Path(step[kind]).name}", Path(step[kind])))
    memory = json.loads((base / "sst-verification/memory/summary.json").read_text())
    native = json.loads((base / "sst-verification/native/result.json").read_text())
    files += [("sst-memory.json", base / "sst-verification/memory/summary.json"),
              ("sst-native.json", base / "sst-verification/native/result.json"),
              ("core-CMakeCache.txt", base / "core/CMakeCache.txt")]
    entries = []
    for name, source in files:
        target = output / name
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(source, target)
        entries.append({"file": str(target.relative_to(output.parent)), "source": str(source),
                        "sha256": sha256_file(target), "bytes": target.stat().st_size})
    report = {"status": "NEW_CHECKS_PASS_HISTORICAL_IDENTITY_AND_PERFORMANCE_GATES_OPEN",
        "checks": checks, "reports": entries, "historical_identity": historical_drift(),
        "core_tests": 29, "focused_python_tests": 56,
        "extraction_exact_rows": 12, "complete_old_matrix_exact_rows": 84,
        "candidate_prediction_rows": 152,
        "sst": {"memory_smokes": memory, "native_smoke": native,
                "plugin": str(base / "sst/libspine_cycle.so"),
                "plugin_sha256": sha256_file(base / "sst/libspine_cycle.so"),
                "candidate_profile_exposed": False},
        "pre_extraction_freeze": {"commit": "d510ea3",
            "archive": str(base / "freeze/source-d510ea3.tar"),
            "sha256": sha256_file(base / "freeze/source-d510ea3.tar")},
        "baseline_admitted": False, "hardware_timing_admitted": False,
        "publication_match_admitted": False, "new_spine_comparison_executed": False}
    atomic_write_json(output.parent / "verification.json", report)
    return report


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    result = package(args.base, args.output)
    print(json.dumps({"status": result["status"], "historical_identity": result["historical_identity"]}))
