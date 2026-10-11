"""Bounded correctness gate for the optional weighted-SSSP four-Little control.

This does not admit publication reproduction or an A4/K4 timing ratio.
"""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import subprocess

from spine_cycle_sim.experiments.campaign_runtime import atomic_write_json, sha256_file
from spine_cycle_sim.experiments.upstream_controls.execution import run_bounded
from .regression import verify_legacy


SSSP_TARGETS = tuple("original_regraph_sssp_" + suffix for suffix in (
    "udf_tests", "frontend_tests", "apply_tests", "round_tests", "source_comparison"))
LEGACY_TARGETS = tuple("original_regraph_" + suffix for suffix in (
    "gather_tests", "frontend_tests", "state_tests", "iteration_tests",
    "source_comparison", "state_comparison"))


def parse_round_rows(contents: str) -> list[dict]:
    rows = [json.loads(line.removeprefix("SSSP_ROUND ")) for line in contents.splitlines()
            if line.startswith("SSSP_ROUND ")]
    if [(row["warm"], row["inactive"]) for row in rows] != [(0, 0), (1, 0), (1, 1)]:
        raise ValueError("missing, repeated or reordered SSSP round fixture")
    for row in rows:
        if (row["checked_words_per_replica"] != 65536 or row["a4_replicas"] != 4
                or row["routed_replicas"] != 2 or row["timing_ratio_admitted"] is not False
                or row["a4_cycles_diagnostic_only"] <= 0
                or row["pressure_cycles"] <= row["a4_cycles_diagnostic_only"]
                or row["a4_read_bytes"] <= 65536 * 4
                or row["a4_write_bytes"] != 65536 * 4 * 4
                or (row["inactive"] and row["active_vertices"] != 0)
                or (not row["inactive"] and row["active_vertices"] <= 0)):
            raise ValueError("SSSP round scope/conservation gate failed")
    return rows


def source_identities(root: Path) -> list[dict]:
    paths = {root / "CMakeLists.txt", root / "cpp/CMakeLists.txt", Path(__file__).resolve()}
    for folder in ("cpp/include", "cpp/src", "cpp/tests/original_regraph"):
        paths.update(p for p in (root / folder).rglob("*") if p.suffix in {".cpp", ".hpp"})
    return [{"path": str(path.relative_to(root)), "sha256": sha256_file(path)}
            for path in sorted(paths)]


def check_build_reference(build: Path, reference: Path) -> None:
    expected = "SPINE_SSSP_UDF_REFERENCE:FILEPATH=" + str(reference)
    if expected not in (build / "CMakeCache.txt").read_text().splitlines():
        raise ValueError("build cache does not identify the requested SSSP HLS reference")


def run(root: Path, build: Path, baseline: Path, reference: Path, output: Path) -> dict:
    if output.exists():
        raise ValueError("refuse to overwrite an existing control run")
    check_build_reference(build, reference)
    frozen = json.loads((baseline / "baseline.json").read_text())
    output.mkdir(parents=True)
    sources = source_identities(root)
    plugin = root / "build/sst/libspine_cycle.so"
    plugin_before = sha256_file(plugin) if plugin.exists() else None
    report = {
        "schema_version": 1, "status": "running", "scope": "weighted_sssp_a4_correctness_only",
        "git_head": subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=root, text=True).strip(),
        "sources": sources, "hls_udf": {"path": str(reference), "sha256": sha256_file(reference)},
        "baseline_manifest_sha256": sha256_file(baseline / "baseline.json"),
        "baseline_compiler": frozen["compiler"], "baseline_git_head": frozen["git_head"],
        "cmake_cache": (build / "CMakeCache.txt").read_text(),
        "cpu_affinity": sorted(os.sched_getaffinity(0)),
        "default_sst_plugin_sha256_before": plugin_before,
        "runs": [], "admission": {"publication_reproduction": False,
            "a4_k4_performance_ratio": False, "new_fpga_timing": False},
    }

    def execute(name: str, command: list[str], timeout: int = 120) -> dict:
        result = run_bounded(command, cwd=root, prefix=output / "raw" / name,
                             timeout=timeout, memory_gib=8, reserve_gib=16)
        report["runs"].append(result)
        atomic_write_json(output / "results.json", report)
        if result["exit_code"] or result["timed_out"]:
            raise RuntimeError("bounded control failed: " + name)
        return result

    try:
        execute("build", ["cmake", "--build", str(build), "--target",
                           *SSSP_TARGETS, *LEGACY_TARGETS, "-j", "2"], 600)
        report["binary_identities"] = [{"path": str(build / "cpp" / target),
                                       "sha256": sha256_file(build / "cpp" / target)}
                                      for target in (*SSSP_TARGETS, *LEGACY_TARGETS)]
        for target in SSSP_TARGETS:
            record = execute(target, [str(build / "cpp" / target)])
            if target.endswith("round_tests"):
                report["round_rows"] = parse_round_rows(Path(record["stdout"]).read_text())
        report["legacy"] = verify_legacy(root, build, baseline,
            {"run_timeout_seconds": 120}, execute)
        if source_identities(root) != sources or sha256_file(reference) != report["hls_udf"]["sha256"]:
            raise ValueError("source changed during control execution")
        plugin_after = sha256_file(plugin) if plugin.exists() else None
        if plugin_before != plugin_after:
            raise ValueError("default SST plugin changed during isolated control")
        report["default_sst_plugin_sha256_after"] = plugin_after
        report["admission"].update(sssp_arithmetic_and_resident_round=True,
                                   default_full_result_regression=True)
        report["status"] = "passed_correctness_only"
    except (OSError, ValueError, RuntimeError) as error:
        report["status"] = "failed"
        report["error"] = str(error)
        raise
    finally:
        atomic_write_json(output / "results.json", report)
    return report


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--build", required=True, type=Path)
    parser.add_argument("--baseline", required=True, type=Path)
    parser.add_argument("--hls-udf", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[3]
    result = run(root, args.build.resolve(), args.baseline.resolve(),
                 args.hls_udf.resolve(), args.output.resolve())
    print(json.dumps({"status": result["status"], "admission": result["admission"]}, sort_keys=True))


if __name__ == "__main__":
    main()
