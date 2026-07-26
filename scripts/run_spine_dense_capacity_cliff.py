#!/usr/bin/env python3
"""Validate Spine's dense cold-family capacity cliff against GraSU support."""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import os
from pathlib import Path
import signal
import subprocess
import sys
import time


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from spine_cycle_sim.experiments.dense_batch_sweep import (  # noqa: E402
    validate_dense_batch_manifest,
    validate_grasu_dense_capacity_rejection,
    validate_spine_dense_capacity_failure,
)
from spine_cycle_sim.experiments.hls_pagerank_real_comparison import (  # noqa: E402
    validate_grasu_pagerank_result,
    validate_spine_pagerank_result,
)
from spine_cycle_sim.experiments.shared_workloads import sha256_file  # noqa: E402


DEFAULT_INPUT = (
    ROOT / "configs/experiments/hls_full_pagerank_dense_batch_sweep_20260726.json"
)
DEFAULT_SPINE_PROFILE = (
    ROOT / "configs/architectures/spine_shared_engine_9c08763.json"
)
DEFAULT_GRASU_PROFILE = (
    ROOT
    / "configs/architectures"
    / "grasu_regraph_weighted_pma_hls_proposed_pagerank_ff13a67.json"
)
DEFAULT_CAPABILITIES = ROOT / "configs/contracts/grasu_regraph_capabilities_v1.json"
DEFAULT_SST = Path("/data/feiyang/sst/bin/sst")
PROFILE_SETS = {
    "legacy": {
        "spine_profile": DEFAULT_SPINE_PROFILE,
        "spine_profile_id": "spine_shared_engine_9c08763",
        "grasu_profile": DEFAULT_GRASU_PROFILE,
        "grasu_profile_id": (
            "grasu_regraph_weighted_pma_hls_proposed_pagerank_ff13a67"
        ),
        "capability_catalog": DEFAULT_CAPABILITIES,
    },
    "candidate10_hls_v3": {
        "spine_profile": ROOT
        / "configs/architectures/spine_candidate10_normalized_v1.json",
        "spine_profile_id": "spine_candidate10_normalized_v1",
        "grasu_profile": ROOT
        / "configs/architectures/grasu_regraph_candidate10_normalized_hls_pagerank_v3.json",
        "grasu_profile_id": (
            "grasu_regraph_candidate10_normalized_hls_pagerank_v3"
        ),
        "capability_catalog": ROOT
        / "configs/contracts/grasu_regraph_candidate10_hls_capabilities_v3.json",
    },
}


def _profile_clock(path: Path, profile_id: str, clock_name: str) -> float:
    profile = json.loads(path.read_text(encoding="utf-8"))
    if profile.get("profile_id") != profile_id:
        raise ValueError(f"profile identity mismatch: {path}")
    clock = next(item for item in profile["clocks"] if item["name"] == clock_name)
    return float(clock["achieved_mhz"])


def _run(command: list[str], log_path: Path, timeout: float) -> tuple[float, int]:
    started = time.monotonic()
    process = subprocess.Popen(
        command,
        cwd=ROOT,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        start_new_session=True,
    )
    try:
        output, _ = process.communicate(timeout=timeout)
    except subprocess.TimeoutExpired as error:
        os.killpg(process.pid, signal.SIGTERM)
        try:
            output, _ = process.communicate(timeout=10.0)
        except subprocess.TimeoutExpired:
            os.killpg(process.pid, signal.SIGKILL)
            output, _ = process.communicate()
        log_path.write_text(output, encoding="utf-8")
        raise RuntimeError(f"child exceeded {timeout:.1f}s") from error
    log_path.write_text(output, encoding="utf-8")
    return time.monotonic() - started, process.returncode


def _commands(run: dict[str, object], args: argparse.Namespace) -> dict[str, list[str]]:
    graph = ROOT / run["graph"]["path"]
    update = ROOT / run["update"]["path"]
    common = [
        "--workload",
        str(graph.resolve()),
        "--update-workload",
        str(update.resolve()),
        "--max-cycles",
        str(args.max_cycles),
        "--sst",
        str(args.sst.resolve()),
        "--lib-dir",
        str(args.lib_dir.resolve()),
    ]
    return {
        "spine": [
            args.python,
            str(ROOT / "scripts/run_sst_spine_vertical.py"),
            "--no-build",
            "--scenario",
            "full_pagerank",
            "--validation-mode",
            "generic",
            "--profile",
            str(args.spine_profile.resolve()),
            "--pagerank-iterations",
            "3",
            "--pagerank-damping",
            "0.85",
            *common,
            "--out-dir",
            str((args.out_dir / str(run["run_id"]) / "spine").resolve()),
        ],
        "grasu_regraph": [
            args.python,
            str(ROOT / "scripts/run_sst_grasu_regraph_hls_pagerank.py"),
            "--no-build",
            "--profile",
            str(args.grasu_profile.resolve()),
            "--capability-catalog",
            str(args.capability_catalog.resolve()),
            *common,
            "--out-dir",
            str(
                (args.out_dir / str(run["run_id"]) / "grasu_regraph").resolve()
            ),
        ],
    }


def _write_csv(path: Path, rows: list[dict[str, object]]) -> None:
    with path.open("w", encoding="utf-8", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input-manifest", type=Path, default=DEFAULT_INPUT)
    parser.add_argument(
        "--profile-set", choices=tuple(PROFILE_SETS), default="legacy"
    )
    parser.add_argument("--spine-profile", type=Path)
    parser.add_argument("--grasu-profile", type=Path)
    parser.add_argument("--capability-catalog", type=Path)
    parser.add_argument("--out-dir", type=Path, required=True)
    parser.add_argument("--run-id", action="append", default=[])
    parser.add_argument("--sst", type=Path, default=DEFAULT_SST)
    parser.add_argument("--lib-dir", type=Path, default=ROOT / "build/sst")
    parser.add_argument("--python", default=sys.executable)
    parser.add_argument("--timeout-seconds", type=float, default=300.0)
    parser.add_argument("--max-cycles", type=int, default=100_000_000)
    parser.add_argument("--no-build", action="store_true")
    args = parser.parse_args()
    if args.timeout_seconds <= 0.0 or args.max_cycles <= 0:
        raise ValueError("timeout and max cycles must be positive")
    profile_set = PROFILE_SETS[args.profile_set]
    args.spine_profile = args.spine_profile or profile_set["spine_profile"]
    args.grasu_profile = args.grasu_profile or profile_set["grasu_profile"]
    args.capability_catalog = (
        args.capability_catalog or profile_set["capability_catalog"]
    )

    manifest = validate_dense_batch_manifest(ROOT, args.input_manifest)
    runs = [
        run
        for run in manifest["runs"]
        if run.get("expected_spine_capacity_status") == "FAIL"
        or run.get("expected_grasu_capacity_status") == "FAIL"
    ]
    if args.run_id:
        selected = set(args.run_id)
        known = {str(run["run_id"]) for run in runs}
        if not selected <= known:
            raise ValueError(f"unknown capacity-cliff run IDs: {sorted(selected - known)}")
        runs = [run for run in runs if run["run_id"] in selected]
    if not runs:
        raise ValueError("no capacity-cliff runs selected")

    spine_mhz = _profile_clock(
        args.spine_profile, str(profile_set["spine_profile_id"]), "data"
    )
    grasu_mhz = _profile_clock(
        args.grasu_profile,
        str(profile_set["grasu_profile_id"]),
        "kernel",
    )
    capabilities = json.loads(args.capability_catalog.read_text(encoding="utf-8"))
    grasu_profile = json.loads(args.grasu_profile.read_text(encoding="utf-8"))
    grasu_profile_hash = sha256_file(args.grasu_profile)
    capability = next(
        item
        for item in capabilities["profiles"]
        if item["profile_id"] == profile_set["grasu_profile_id"]
    )
    if capability["profile_sha256"] != grasu_profile_hash:
        raise ValueError("GraSU capability/profile hash mismatch")
    if not args.no_build:
        subprocess.run(["make", "-C", "cpp/sst", "-j2"], cwd=ROOT, check=True)
    args.out_dir.mkdir(parents=True, exist_ok=True)

    rows: list[dict[str, object]] = []
    started = time.monotonic()
    for run in runs:
        commands = _commands(run, args)
        run_dir = args.out_dir / str(run["run_id"])
        spine_dir = run_dir / "spine"
        grasu_dir = run_dir / "grasu_regraph"
        spine_dir.mkdir(parents=True, exist_ok=True)
        grasu_dir.mkdir(parents=True, exist_ok=True)
        spine_wall, spine_rc = _run(
            commands["spine"], spine_dir / "parent_driver.log", args.timeout_seconds
        )
        if run["expected_spine_capacity_status"] == "FAIL":
            spine_result_path = spine_dir / "result.json"
            spine_result = json.loads(spine_result_path.read_text(encoding="utf-8"))
            spine_problems = validate_spine_dense_capacity_failure(run, spine_result)
            if spine_rc == 0 or spine_problems:
                raise RuntimeError(
                    f"{run['run_id']} did not reproduce the expected Spine capacity "
                    f"failure: rc={spine_rc} problems={spine_problems}"
                )
            spine_status = "EXPECTED_CAPACITY_FAIL"
            spine_failure = str(spine_result["failure"])
            spine_cycles = int(spine_result["cycles"])
            spine_requests = int(spine_result["backend_requests"])
        else:
            if spine_rc != 0:
                raise RuntimeError(f"{run['run_id']} Spine child failed rc={spine_rc}")
            spine_result_path = spine_dir / "summary.json"
            spine_result = json.loads(spine_result_path.read_text(encoding="utf-8"))
            spine_problems = validate_spine_pagerank_result(
                run,
                spine_result,
                expected_profile_id=str(profile_set["spine_profile_id"]),
                expected_core_mhz=spine_mhz,
                iterations=3,
                damping=0.85,
            )
            if spine_problems:
                raise RuntimeError(
                    f"{run['run_id']} Spine correctness gates failed: {spine_problems}"
                )
            spine_status = "PASS"
            spine_failure = ""
            spine_cycles = int(spine_result["cycles"])
            spine_requests = int(spine_result["backend_requests"])

        grasu_manifest_path = grasu_dir / "manifest.json"
        if run["expected_grasu_capacity_status"] == "FAIL":
            grasu_problems = validate_grasu_dense_capacity_rejection(
                run, grasu_profile
            )
            if grasu_problems:
                raise RuntimeError(
                    f"{run['run_id']} GraSU profile-capacity gates failed: "
                    f"{grasu_problems}"
                )
            grasu_wall = 0.0
            grasu_status = "EXPECTED_PROFILE_CAPACITY_FAIL"
            grasu_cycles: int | None = None
            grasu_requests: int | None = None
            grasu_correctness: int | None = None
            grasu_manifest_hash = ""
        else:
            grasu_wall, grasu_rc = _run(
                commands["grasu_regraph"],
                grasu_dir / "parent_driver.log",
                args.timeout_seconds,
            )
            if grasu_rc != 0:
                raise RuntimeError(f"{run['run_id']} GraSU child failed rc={grasu_rc}")
            grasu_child = json.loads(grasu_manifest_path.read_text(encoding="utf-8"))
            grasu_problems = validate_grasu_pagerank_result(
                run,
                grasu_child,
                expected_profile_sha256=grasu_profile_hash,
                expected_core_mhz=grasu_mhz,
                iterations=3,
                damping=0.85,
            )
            if grasu_problems:
                raise RuntimeError(
                    f"{run['run_id']} GraSU correctness gates failed: {grasu_problems}"
                )
            grasu_result = grasu_child["result"]
            grasu_status = "PASS"
            grasu_cycles = int(grasu_result["cycles"])
            grasu_requests = int(grasu_result["backend_requests"])
            grasu_correctness = int(grasu_result["correctness_mismatches"])
            grasu_manifest_hash = sha256_file(grasu_manifest_path)
        rows.append(
            {
                "run_id": run["run_id"],
                "pattern": run["pattern"],
                "batch_size": run["batch_size"],
                "initial_edges": run["graph"]["records"],
                "final_edges": run["final_edges"],
                "spine_status": spine_status,
                "spine_failure": spine_failure,
                "spine_cycles": spine_cycles,
                "spine_ms": float(spine_cycles)
                / (spine_mhz * 1_000.0),
                "spine_backend_requests": spine_requests,
                "spine_host_wall_seconds": spine_wall,
                "grasu_status": grasu_status,
                "grasu_correctness_mismatches": grasu_correctness,
                "grasu_cycles": grasu_cycles,
                "grasu_ms": (
                    None
                    if grasu_cycles is None
                    else float(grasu_cycles) / (grasu_mhz * 1_000.0)
                ),
                "grasu_backend_requests": grasu_requests,
                "grasu_host_wall_seconds": grasu_wall,
                "performance_ratio_valid": False,
                "performance_ratio_reason": (
                    "At least one architecture rejects the batch before a common "
                    "successful timing window exists"
                ),
                "spine_result_sha256": sha256_file(spine_result_path),
                "grasu_manifest_sha256": grasu_manifest_hash,
            }
        )
        print(
            f"PASS {run['run_id']}: Spine={spine_status} GraSU={grasu_status}",
            flush=True,
        )

    rows_path = args.out_dir / "capacity_rows.csv"
    _write_csv(rows_path, rows)
    execution_files = [
        Path(__file__),
        ROOT / "spine_cycle_sim/experiments/dense_batch_sweep.py",
        ROOT / "scripts/run_sst_spine_vertical.py",
        ROOT / "scripts/run_sst_grasu_regraph_hls_pagerank.py",
        args.input_manifest,
        args.spine_profile,
        args.grasu_profile,
        args.capability_catalog,
        args.lib_dir / "libspine_cycle.so",
    ]
    evidence = {
        "schema_version": 1,
        "matrix_id": "spine_full_pagerank_dense_capacity_cliff_20260726",
        "status": "PASS",
        "claim_class": "architecture_capacity_support_boundary",
        "algorithm": "full_pagerank",
        "profile_set": args.profile_set,
        "input_manifest": str(args.input_manifest.resolve()),
        "input_manifest_sha256": sha256_file(args.input_manifest),
        "selected_run_ids": [run["run_id"] for run in runs],
        "all_expected_capacity_outcomes_reproduced": True,
        "all_successful_runs_correct": True,
        "performance_ratio_valid": False,
        "performance_ratio_reason": (
            "Capacity support is compared, but latency ratios are undefined when "
            "either architecture cannot enter the common successful timing window."
        ),
        "spine_profile": str(args.spine_profile.resolve()),
        "spine_profile_sha256": sha256_file(args.spine_profile),
        "grasu_profile": str(args.grasu_profile.resolve()),
        "grasu_profile_sha256": grasu_profile_hash,
        "capability_catalog": str(args.capability_catalog.resolve()),
        "capability_catalog_sha256": sha256_file(args.capability_catalog),
        "matrix_wall_seconds": time.monotonic() - started,
        "capacity_rows_sha256": sha256_file(rows_path),
        "execution_sha256": hashlib.sha256(
            b"".join(path.resolve().read_bytes() for path in execution_files)
        ).hexdigest(),
        "limitations": [
            "GraSU failures above 4096 updates are static checks against the "
            "pinned PageRank profile; no latency ratio is inferred from a "
            "capacity rejection.",
            "Spine capacity is the current cold-family L1 layout boundary for "
            "this intentionally single-family workload.",
            "Capacity evidence is not a performance comparison.",
        ],
    }
    (args.out_dir / "matrix_manifest.json").write_text(
        json.dumps(evidence, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    print(f"PASS dense capacity cliff matrix: runs={len(rows)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
