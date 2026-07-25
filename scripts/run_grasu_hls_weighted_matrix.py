#!/usr/bin/env python3
"""Run the frozen ff13a67 weighted-HLS correctness and activity matrix."""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
from pathlib import Path
import subprocess
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.run_sst_grasu_regraph_hls_weighted import (  # noqa: E402
    DEFAULT_CAPABILITY_CATALOG,
    DEFAULT_PROFILE,
    DEFAULT_SST,
    sha256,
)
from spine_cycle_sim.experiments.hls_weighted_workloads import (  # noqa: E402
    HlsWeightedFixture,
    hls_weighted_fixtures,
)
from spine_cycle_sim.experiments.shared_workloads import write_slice  # noqa: E402


def _implementation_sha256(paths: list[Path]) -> str:
    digest = hashlib.sha256()
    for path in paths:
        resolved = path.resolve()
        digest.update(str(resolved).encode("utf-8"))
        digest.update(b"\0")
        digest.update(resolved.read_bytes())
        digest.update(b"\0")
    return digest.hexdigest()


def _write_rows(path: Path, rows: list[dict[str, object]]) -> None:
    with path.open("w", encoding="utf-8", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)


def _select_fixtures(
    fixtures: tuple[HlsWeightedFixture, ...],
    case_ids: list[str],
    roles: list[str],
    limit: int | None,
) -> list[HlsWeightedFixture]:
    known = {fixture.fixture_id for fixture in fixtures}
    unknown = sorted(set(case_ids) - known)
    if unknown:
        raise ValueError(f"unknown HLS weighted case IDs: {unknown}")
    selected = [
        fixture
        for fixture in fixtures
        if (not case_ids or fixture.fixture_id in case_ids)
        and (not roles or fixture.role in roles)
    ]
    if limit is not None:
        if limit <= 0:
            raise ValueError("limit must be positive")
        selected = selected[:limit]
    if not selected:
        raise ValueError("HLS weighted matrix selection is empty")
    return selected


def _run_fixture(
    fixture: HlsWeightedFixture,
    *,
    args: argparse.Namespace,
) -> dict[str, object]:
    case_dir = args.out_dir / fixture.fixture_id
    workload_dir = args.out_dir / "workloads"
    case_dir.mkdir(parents=True, exist_ok=True)
    workload_dir.mkdir(parents=True, exist_ok=True)
    initial_path = workload_dir / f"{fixture.fixture_id}.slice"
    update_path = workload_dir / f"{fixture.fixture_id}_update.slice"
    write_slice(initial_path, fixture.graph)
    write_slice(update_path, fixture.update)
    command = [
        args.python,
        str(ROOT / "scripts" / "run_sst_grasu_regraph_hls_weighted.py"),
        "--no-build",
        "--profile",
        str(args.profile.resolve()),
        "--capability-catalog",
        str(args.capability_catalog.resolve()),
        "--workload",
        str(initial_path.resolve()),
        "--update-workload",
        str(update_path.resolve()),
        "--source",
        str(fixture.source),
        "--out-dir",
        str(case_dir.resolve()),
        "--sst",
        str(args.sst.resolve()),
        "--lib-dir",
        str(args.lib_dir.resolve()),
        "--max-cycles",
        str(args.max_cycles),
    ]
    started = time.monotonic()
    completed = subprocess.run(
        command,
        cwd=ROOT,
        check=False,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        timeout=args.timeout_seconds,
    )
    driver_wall_seconds = time.monotonic() - started
    (case_dir / "driver.log").write_text(completed.stdout, encoding="utf-8")
    if completed.returncode != 0:
        raise RuntimeError(
            f"{fixture.fixture_id} failed with rc={completed.returncode}; "
            f"see {case_dir / 'driver.log'}"
        )
    manifest = json.loads((case_dir / "manifest.json").read_text(encoding="utf-8"))
    result = manifest["result"]
    dram = manifest["dram"]
    if manifest.get("status") != "PASS" or result.get("success") is not True:
        raise RuntimeError(f"{fixture.fixture_id} child manifest did not pass")
    core_mhz = float(result["core_mhz"])
    update_cycles = int(result["update_cycles"])
    total_cycles = int(result["cycles"])
    logical_updates = int(result["logical_updates"])
    physical_updates = int(result["physical_updates"])
    return {
        "case_id": fixture.fixture_id,
        "role": fixture.role,
        "family": fixture.family,
        "vertices": fixture.graph.vertices,
        "initial_edges": len(fixture.graph.records),
        "logical_updates": logical_updates,
        "physical_updates": physical_updates,
        "physical_per_logical": physical_updates / logical_updates,
        "cycles": total_cycles,
        "update_cycles": update_cycles,
        "compute_cycles": int(result["compute_cycles"]),
        "simulated_ms": total_cycles / (core_mhz * 1_000.0),
        "logical_update_edges_per_second": logical_updates
        * core_mhz
        * 1_000_000.0
        / update_cycles,
        "physical_update_ops_per_second": physical_updates
        * core_mhz
        * 1_000_000.0
        / update_cycles,
        "e2e_logical_updates_per_second": logical_updates
        * core_mhz
        * 1_000_000.0
        / total_cycles,
        "correctness_mismatches": int(result["correctness_mismatches"]),
        "supersteps": int(result["supersteps"]),
        "update_pma_reads": int(result["update_pma_reads"]),
        "update_pma_writes": int(result["update_pma_writes"]),
        "compute_pma_segment_reads": int(result["compute_pma_segment_reads"]),
        "compute_pma_slots": int(result["compute_pma_slots"]),
        "compute_live_edges": int(result["compute_live_edges"]),
        "compute_active_edges": int(result["compute_active_edges"]),
        "update_read_bytes": int(result["update_read_bytes"]),
        "update_write_bytes": int(result["update_write_bytes"]),
        "compute_read_bytes": int(result["compute_read_bytes"]),
        "compute_write_bytes": int(result["compute_write_bytes"]),
        "backend_requests": int(result["backend_requests"]),
        "axi_backend_stalls": int(result["axi_backend_stalls"]),
        "axis_push_stalls": int(result["axis_push_stalls"]),
        "dram_reads": int(dram["reads"]),
        "dram_writes": int(dram["writes"]),
        "dram_activates": int(dram["activates"]),
        "dram_precharges": int(dram["precharges"]),
        "dram_energy_pj": float(dram["total_energy_pj"]),
        "driver_wall_seconds": driver_wall_seconds,
        "child_manifest_sha256": sha256(case_dir / "manifest.json"),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out-dir", type=Path, required=True)
    parser.add_argument("--profile", type=Path, default=DEFAULT_PROFILE)
    parser.add_argument(
        "--capability-catalog", type=Path, default=DEFAULT_CAPABILITY_CATALOG
    )
    parser.add_argument("--sst", type=Path, default=DEFAULT_SST)
    parser.add_argument("--lib-dir", type=Path, default=ROOT / "build" / "sst")
    parser.add_argument("--python", default=sys.executable)
    parser.add_argument("--case-id", action="append", default=[])
    parser.add_argument("--role", action="append", default=[])
    parser.add_argument("--limit", type=int)
    parser.add_argument("--timeout-seconds", type=float, default=120.0)
    parser.add_argument("--max-cycles", type=int, default=30_000_000)
    parser.add_argument("--no-build", action="store_true")
    args = parser.parse_args()
    if args.timeout_seconds <= 0.0 or args.max_cycles <= 0:
        raise ValueError("timeout and max cycles must be positive")
    fixtures = hls_weighted_fixtures()
    selected = _select_fixtures(fixtures, args.case_id, args.role, args.limit)
    if not args.no_build:
        subprocess.run(["make", "-C", "cpp/sst", "-j2"], cwd=ROOT, check=True)
    args.out_dir.mkdir(parents=True, exist_ok=True)
    implementation_sha256 = _implementation_sha256(
        [
            Path(__file__),
            ROOT / "scripts" / "run_sst_grasu_regraph_hls_weighted.py",
            ROOT
            / "spine_cycle_sim"
            / "experiments"
            / "hls_weighted_workloads.py",
            args.profile,
            args.capability_catalog,
            args.lib_dir / "libspine_cycle.so",
            args.sst,
        ]
    )
    started = time.monotonic()
    rows: list[dict[str, object]] = []
    for fixture in selected:
        row = _run_fixture(fixture, args=args)
        rows.append(row)
        print(
            f"PASS {fixture.fixture_id}: cycles={row['cycles']} "
            f"logical={row['logical_updates']} physical={row['physical_updates']} "
            f"wall_s={float(row['driver_wall_seconds']):.3f}",
            flush=True,
        )
    matrix_wall_seconds = time.monotonic() - started
    _write_rows(args.out_dir / "rows.csv", rows)
    complete = len(selected) == len(fixtures) and not args.case_id and not args.role
    manifest = {
        "schema_version": 1,
        "matrix_id": "grasu_hls_weighted_ff13a67_microbench_20260726",
        "claim_class": (
            "complete_hls_aligned_synthetic_validation_matrix"
            if complete
            else "filtered_hls_aligned_synthetic_validation_subset"
        ),
        "profile": str(args.profile.resolve()),
        "profile_sha256": sha256(args.profile.resolve()),
        "capability_catalog": str(args.capability_catalog.resolve()),
        "capability_catalog_sha256": sha256(args.capability_catalog.resolve()),
        "implementation_sha256": implementation_sha256,
        "selected_case_ids": [fixture.fixture_id for fixture in selected],
        "total_frozen_cases": len(fixtures),
        "result_rows": len(rows),
        "all_correct": all(row["correctness_mismatches"] == 0 for row in rows),
        "matrix_wall_seconds": matrix_wall_seconds,
        "limitations": [
            "Synthetic weighted SSSP microbenchmarks only.",
            "The ff13a67 profile executes exactly four host supersteps.",
            "Timing is execution-driven SST/DRAMSim3, not cycle-calibrated hw.",
            "Sequential/random access classification and total PPA remain open.",
        ],
        "status": "PASS",
    }
    (args.out_dir / "matrix_manifest.json").write_text(
        json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    print(
        f"PASS weighted-HLS matrix: rows={len(rows)} complete={complete} "
        f"wall_s={matrix_wall_seconds:.3f}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
