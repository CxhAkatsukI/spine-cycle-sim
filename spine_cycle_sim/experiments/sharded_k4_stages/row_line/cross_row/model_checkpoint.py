"""Seal legacy equivalence, core tests and the unfitted twelve-case RTL diagnostic."""

import argparse
import hashlib
import json
from pathlib import Path

from spine_cycle_sim.experiments.campaign_runtime import atomic_write_json, sha256_file
from spine_cycle_sim.experiments.original_regraph_execution.sssp_real_round.delivery import seal
from spine_cycle_sim.experiments.refactor_equivalence import compare_runs
from ..delivery import raw_files
from ..evidence import bounded
from ..model_archive import extracted
from ..model_recheck import read_json, source_files
from .model_timing_evidence import recheck as recheck_timing


def recheck(run: Path) -> dict:
    frozen = read_json(run / "pre_edit_source_index.json")
    if sha256_file(run / "pre_edit_source.tar.gz") != frozen["archive_sha256"]:
        raise ValueError("pre-edit source archive differs")
    before = source_files(run / "pre_edit_source.tar.gz", frozen)
    baseline = read_json(run / "baseline-isolated/identity.json")
    contract_bytes = before["configs/experiments/grasu_component_refactor_v1.json"]
    if (json.loads(before["baseline_identity.json"]) != baseline
            or hashlib.sha256(contract_bytes).hexdigest() != baseline["contract_sha256"]):
        raise ValueError("pre-edit baseline or matrix differs")
    legacy = compare_runs(json.loads(contract_bytes), run / "baseline-isolated", run / "legacy-after")
    plugin = run / "plugin/libspine_cycle.so"
    if (legacy["status"] != "PASS" or legacy["correctness_admitted_cases"] != 5 or legacy["known_rejections"]
            or legacy != read_json(run / "legacy-after/equivalence.json")
            or legacy["candidate_identity"]["plugin_sha256"] != sha256_file(plugin)):
        raise ValueError("legacy full-result equivalence differs")
    for step in ("configure", "build-v2", "build-final", "plugin-build-final", "core-tests-final",
                 "baseline_isolated_campaign", "legacy-after-campaign", "python-tests-final"):
        path = run / (step + ".resources.json")
        record = read_json(path)
        bounded(path, record["command"], record["cwd"], record["timeout_seconds"], record["tree_memory_gib"])
    log = (run / "core/Testing/Temporary/LastTest.log").read_text()
    if (log.count("Test Passed.") != 27 or "Test Failed." in log
            or "Cross-row structural model PASS cases=210" not in log
            or "100% tests passed, 0 tests failed out of 27" not in (run / "core-tests-final.stdout.txt").read_text()):
        raise ValueError("complete core test admission differs")
    timing = recheck_timing(run / "timing", run / "core/cpp/routed_pma_adapter_tests")
    return {"status": "CROSS_ROW_MODEL_FUNCTIONAL_TRAFFIC_AND_LEGACY_PASS_NOT_CALIBRATED",
            "legacy_cases": legacy["cases"], "core_executables_passed": 27, "rtl_diagnostic": timing,
            "failed_default_plugin_baseline_retained": True,
            "hardware_timing_admitted": False, "original_A4_comparison_complete": False}


def deliver(run: Path, destination: Path) -> dict:
    if destination.exists():
        raise FileExistsError("fresh checkpoint destination required")
    report = recheck(run)
    selected = []
    for directory in ("baseline", "baseline-isolated", "legacy-after", "timing"):
        selected += raw_files(run / directory, directory)
    for pattern in ("*.json", "*.txt", "*.tar.gz"):
        selected += [(path, path.name) for path in sorted(run.glob(pattern)) if path.is_file()]
    selected += [(run / "plugin/libspine_cycle.so", "plugin/libspine_cycle.so"),
                 (run / "core/cpp/routed_pma_adapter_tests", "core/cpp/routed_pma_adapter_tests"),
                 (run / "core/Testing/Temporary/LastTest.log", "core/Testing/Temporary/LastTest.log"),
                 (run / "core/CMakeCache.txt", "core/CMakeCache.txt")]
    for pattern in ("flags.make", "link.txt"):
        selected += [(path, path.relative_to(run).as_posix()) for path in sorted((run / "core").rglob(pattern))]
    destination.mkdir(parents=True)
    archive = destination / "raw_checkpoint.tar.gz"
    entries = seal(selected, archive)
    atomic_write_json(destination / "results.json", report)
    atomic_write_json(destination / "verification.json", {
        "status": report["status"], "files": entries, "archive_sha256": sha256_file(archive),
        "archive_bytes": archive.stat().st_size, "results_sha256": sha256_file(destination / "results.json"),
        "claim": "portable_functional_traffic_and_legacy_recheck_not_FPGA_calibration_or_A4_comparison"})
    return report


def verify(destination: Path) -> dict:
    record = read_json(destination / "verification.json")
    if sha256_file(destination / "results.json") != record["results_sha256"]:
        raise ValueError("sealed checkpoint conclusion differs")
    with extracted(destination / "raw_checkpoint.tar.gz", record, max_bytes=256 * 1024**2) as root:
        report = recheck(root)
    if report != read_json(destination / "results.json") or record["status"] != report["status"]:
        raise ValueError("portable checkpoint conclusion differs")
    return report


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run", type=Path)
    parser.add_argument("--destination", type=Path, required=True)
    parser.add_argument("--verify-only", action="store_true")
    args = parser.parse_args()
    if not args.verify_only:
        if not args.run:
            parser.error("--run required for delivery")
        deliver(args.run.resolve(), args.destination.resolve())
    print(json.dumps({"status": verify(args.destination.resolve())["status"], "portable_recheck": "PASS"}))


if __name__ == "__main__":
    main()
