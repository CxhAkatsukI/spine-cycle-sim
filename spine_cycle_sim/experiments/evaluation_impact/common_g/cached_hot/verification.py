"""Archive completed cache regressions, including failed diagnostic attempts."""

import argparse
import json
from pathlib import Path
import tarfile

from spine_cycle_sim.experiments.campaign_runtime import atomic_write_json, sha256_file
from ..hot_lanes.verification import historical_drift


def package(base, previous, output):
    first = json.loads((base / "matrix-v1/results.json").read_text())
    final = json.loads((base / "matrix-v2/results.json").read_text())
    if first["status"] != "FAILED_RETAINED" or first["errors"] or \
            first.get("error") != "ValueError('cache preload/writeback cannot have zero time')" or \
            final["status"] != "CACHED_G_PREDICTION_VALIDATED_REFERENCE_TIMING_OPEN" or \
            first["rows"] != final["rows"] or len(final["rows"]) != 190:
        raise ValueError("retained analyzer failure or complete replay differs")
    focused = json.loads((base / "python-verification-v2/results.json").read_text())
    historical = json.loads((base / "python-verification-v2/historical.json").read_text())
    sst = json.loads((base / "sst-verification/results.json").read_text())
    if focused["status"] != "FOCUSED_PASS" or len(focused["steps"]) != 1 or \
            sst["status"] != "DEFAULT_SST_SMOKES_PASS_NOT_CANDIDATE_TIMING" or len(sst["steps"]) != 3 or \
            historical["status"] != "HISTORICAL_IDENTITY_FAILURES_RETAINED" or \
            historical["identity_drift"] != historical_drift():
        raise ValueError("verification scope or historical failure set changed")
    checks = []
    sources = {}

    def include(path):
        sources[str(path.relative_to(base))] = path

    def check(step, expected, name):
        if step["exit_code"] != expected or step["timed_out"]:
            raise ValueError("unexpected verification outcome: " + name)
        checks.append({"name": name, "expected_exit_code": expected, **step})
        for kind in ("stdout", "stderr"):
            include(Path(step[kind]))

    for name, expected in (("configure", 0), ("build", 0), ("ctest", 8),
            ("test-diagnostic-build", 0), ("test-diagnostic", 1),
            ("ack-fix-build", 0), ("ctest-v2", 0)):
        path = base / "raw" / (name + ".resources.json")
        include(path)
        check(json.loads(path.read_text()), expected, name)
    path = base / "sst-verification/build.resources.json"
    include(path)
    check(json.loads(path.read_text()), 0, "fresh-sst-build")
    for index, step in enumerate(sst["steps"]):
        check(step, 0, f"default-sst/{index}")
    check(focused["steps"][0], 0, "focused-python")
    check(historical["step"], 1, "retained-historical-identities")
    if "100% tests passed, 0 tests failed out of 30" not in \
            (base / "raw/ctest-v2.stdout.txt").read_text() or \
            "Ran 80 tests" not in Path(focused["steps"][0]["stderr"]).read_text():
        raise ValueError("complete declared regression counts required")
    sst_exact = []
    for name in ("memory/summary.json", "native/result.json"):
        path = base / "sst-verification" / name
        old = previous / "sst-verification" / name
        if json.loads(path.read_text()) != json.loads(old.read_text()):
            raise ValueError("default SST behavior changed: " + name)
        include(path)
        sst_exact.append({"file": name, "previous": str(old), "previous_sha256": sha256_file(old)})
    for name in ("before.json", "analyzer-fix-freeze/manifest.json", "core/CMakeCache.txt",
            "core/compile_commands.json", "matrix-v1/results.json",
            "python-verification-v2/results.json", "python-verification-v2/historical.json",
            "sst-verification/results.json"):
        include(base / name)
    output.mkdir(parents=True, exist_ok=False)
    archive = output / "regressions.tar.gz"
    members = []
    with tarfile.open(archive, "w:gz") as handle:
        for name, path in sorted(sources.items()):
            handle.add(path, arcname=name, recursive=False)
            members.append({"member": name, "source": str(path),
                            "sha256": sha256_file(path), "bytes": path.stat().st_size})
    identities = []
    for name in ("sources.tar.gz", "analyzer-fix-freeze/sources.tar.gz",
            "core/cpp/libspine_cycle_core.a", "core/cpp/liboriginal_grasu_cycle.a",
            "sst/libspine_cycle.so", "matrix-v2/build/common_g_execution"):
        path = base / name
        identities.append({"path": str(path), "sha256": sha256_file(path), "bytes": path.stat().st_size})
    report = {"status": "REGRESSIONS_PASS_PERFORMANCE_REFERENCE_AND_HARDWARE_GATES_OPEN",
        "archive": {"file": archive.name, "sha256": sha256_file(archive), "bytes": archive.stat().st_size},
        "members": members, "checks": checks, "machine_local_identities": identities,
        "core_tests": 30, "focused_python_tests": 80, "prediction_rows": 190,
        "old_checkpoint_exact_rows": 152, "failed_analyzer_attempt_exact_replay_rows": 190,
        "sst_exact_default_smokes": sst_exact, "historical_identity": historical["identity_drift"],
        "baseline_admitted": False, "hardware_timing_admitted": False,
        "publication_match_admitted": False, "candidate_sst_timing_admitted": False,
        "new_spine_comparison_executed": False}
    atomic_write_json(output / "index.json", report)
    return report


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    for key in ("base", "previous", "output"):
        parser.add_argument("--" + key, type=Path, required=True)
    args = parser.parse_args()
    result = package(args.base, args.previous, args.output)
    print(json.dumps({"status": result["status"], "core_tests": result["core_tests"]}))
