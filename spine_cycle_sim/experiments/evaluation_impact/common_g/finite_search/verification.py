"""Archive finite-search regressions without promoting predicted timing."""

import argparse
import json
from pathlib import Path
import tarfile

from spine_cycle_sim.experiments.campaign_runtime import atomic_write_json, sha256_file


STEPS = {"configure": 0, "build": 2, "build-all-v2": 0,
    "test-diagnostic-build": 0, "ctest-v1": 8, "finite-reorder-build-v1": 0,
    "build-all-v3": 0, "finite-tests-v2": 0, "ctest-v2": 0,
    "sst-build-v1": 0, "focused-tests-v1": 0}


def check_outcome(step, expected, name):
    if step["exit_code"] != expected or step["timed_out"] or \
            not 0 < step["memory_limit_gib"] <= 2 or step["reserve_gib"] < 8:
        raise ValueError("unexpected or unbounded verification outcome: " + name)
    return {"name": name, "expected_exit_code": expected, **step}


def package(base, previous, output):
    matrix = json.loads((base / "matrix-v1/results.json").read_text())
    if matrix["status"] != "G_FINITE_SEARCH_PREDICTIONS_CHECKED" or \
            len(matrix["rows"]) != 228 or matrix["exact_replayed_rows"] != 190:
        raise ValueError("completed finite-stage matrix required")
    sst = json.loads((base / "sst-verification/results.json").read_text())
    if sst["status"] != "DEFAULT_SST_SMOKES_PASS_NOT_CANDIDATE_TIMING" or len(sst["steps"]) != 3:
        raise ValueError("three fresh default SST checks required")
    checks, sources = [], {}

    def include(path):
        sources[str(path.relative_to(base))] = path

    def record(step, expected, name):
        checks.append(check_outcome(step, expected, name))
        for key in ("stdout", "stderr"):
            include(Path(step[key]))
        include(Path(step["stdout"].replace(".stdout.txt", ".resources.json")))

    for name, expected in STEPS.items():
        record(json.loads((base / (name + ".resources.json")).read_text()), expected, name)
    for index, step in enumerate(sst["steps"]):
        record(step, 0, f"default-sst/{index}")
    for path, marker in (("build.stderr.txt", "No rule to make target 'common_g_execution'"),
            ("ctest-v1.stdout.txt", "finite search requires ordered update AXI responses"),
            ("ctest-v2.stdout.txt", "100% tests passed, 0 tests failed out of 31"),
            ("focused-tests-v1.stderr.txt", "Ran 95 tests")):
        if marker not in (base / path).read_text():
            raise ValueError("declared verification scope or retained failure differs: " + path)
    defaults = []
    for name in ("memory/summary.json", "native/result.json"):
        path, old = base / "sst-verification" / name, previous / "sst-verification" / name
        if json.loads(path.read_text()) != json.loads(old.read_text()):
            raise ValueError("default SST behavior changed: " + name)
        include(path)
        defaults.append({"file": name, "previous": str(old), "previous_sha256": sha256_file(old)})
    for name in ("pre_edit/freeze.json", "pre_edit/pre_edit.diff", "pre_edit/matrix-results.json",
            "pre_edit/source-controls-v4-results.json", "build/CMakeCache.txt",
            "build/compile_commands.json", "sst-verification/results.json"):
        include(base / name)
    identities = []
    for name in ("pre_edit/sources.tar.gz", "build/cpp/libspine_cycle_core.a",
            "build/cpp/liboriginal_grasu_cycle.a", "sst/libspine_cycle.so",
            "matrix-v1/build/common_g_execution"):
        path = base / name
        identities.append({"path": str(path), "sha256": sha256_file(path), "bytes": path.stat().st_size})
    output.mkdir(parents=True, exist_ok=False)
    archive, members = output / "regressions.tar.gz", []
    with tarfile.open(archive, "w:gz") as handle:
        for name, path in sorted(sources.items()):
            handle.add(path, arcname=name, recursive=False)
            members.append({"member": name, "source": str(path),
                            "sha256": sha256_file(path), "bytes": path.stat().st_size})
    result = {"status": "FINITE_SEARCH_REGRESSIONS_PASS_HARDWARE_AND_PUBLICATION_OPEN",
        "archive": {"file": archive.name, "sha256": sha256_file(archive), "bytes": archive.stat().st_size},
        "members": members, "checks": checks, "machine_local_identities": identities,
        "core_tests": 31, "focused_python_tests": 95, "prediction_rows": 228,
        "exact_replayed_rows": 190, "sst_exact_default_smokes": defaults,
        "retained_failures": ["invalid root build target", "valid out-of-order AXI rejected"],
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
