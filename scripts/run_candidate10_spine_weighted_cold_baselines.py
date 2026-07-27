#!/usr/bin/env python3
"""Run quiescent-prefix Spine SSSP baselines for DRAM phase subtraction."""

from __future__ import annotations

import argparse
from concurrent.futures import ThreadPoolExecutor, as_completed
import csv
import hashlib
import json
from pathlib import Path
import subprocess
import sys
import time
from typing import Mapping


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from spine_cycle_sim.experiments.comparison_analysis import (  # noqa: E402
    aggregate_dram_stats,
    sha256_file,
)


DEFAULT_MANIFEST = (
    ROOT
    / "configs/experiments/candidate10_grasu_temporal_compact_batches_v1_20260727.json"
)
DEFAULT_PROFILE = ROOT / "configs/architectures/spine_candidate10_normalized_v1.json"
DEFAULT_SST = Path("/data/feiyang/sst/bin/sst")


def _validate_cold_prefix(
    cold: Mapping[str, object], dynamic: Mapping[str, object]
) -> list[str]:
    checks = {
        "success": cold.get("success") is True,
        "correctness": all(
            int(cold.get(field, -1)) == 0
            for field in (
                "correctness_mismatches",
                "architecture_correctness_mismatches",
                "mathematical_correctness_mismatches",
            )
        ),
        "cycles": cold.get("cycles") == dynamic.get("cold_cycles"),
        "backend_requests": cold.get("backend_requests")
        == dynamic.get("cold_backend_requests"),
        "final_values": cold.get("final_values")
        == dynamic.get("cold_final_values"),
        "rounds": cold.get("rounds") == dynamic.get("cold_rounds"),
        "round_cycles": cold.get("round_cycles")
        == dynamic.get("cold_round_cycles"),
        "maintenance_cycles": cold.get("maintenance_cycles")
        == dynamic.get("cold_maintenance_cycles"),
        "profile": cold.get("architecture_profile_id")
        == dynamic.get("architecture_profile_id"),
        "plugin": cold.get("sst_plugin_sha256")
        == dynamic.get("sst_plugin_sha256"),
    }
    return [name for name, passed in checks.items() if not passed]


def _restore_final_values(
    out_dir: Path, summary: dict[str, object]
) -> dict[str, object]:
    if isinstance(summary.get("final_values"), list):
        return summary
    expected_count = int(summary.get("final_values_count", -1))
    expected_sha256 = summary.get("final_values_sha256")
    if expected_count <= 0 or not isinstance(expected_sha256, str):
        raise RuntimeError("cold summary has no recoverable final-value vector")
    raw = json.loads((out_dir / "result.json").read_text(encoding="utf-8"))
    final_values = raw.get("final_values")
    if not isinstance(final_values, list) or len(final_values) != expected_count:
        raise RuntimeError("cold raw final-value count does not match summary")
    encoded = json.dumps(final_values, separators=(",", ":")).encode("ascii")
    if hashlib.sha256(encoded).hexdigest() != expected_sha256:
        raise RuntimeError("cold raw final-value hash does not match summary")
    return {**summary, "final_values": final_values}


def _command(run: Mapping[str, object], args: argparse.Namespace, out_dir: Path) -> list[str]:
    graph = ROOT / run["graph"]["path"]  # type: ignore[index]
    return [
        args.python,
        str(ROOT / "scripts/run_sst_spine_vertical.py"),
        "--no-build",
        "--scenario",
        "weighted_sssp",
        "--validation-mode",
        "generic",
        "--profile",
        str(args.profile.resolve()),
        "--workload",
        str(graph.resolve()),
        "--source",
        "0",
        "--max-rounds",
        "256",
        "--max-cycles",
        str(args.max_cycles),
        "--sst",
        str(args.sst.resolve()),
        "--lib-dir",
        str(args.lib_dir.resolve()),
        "--out-dir",
        str(out_dir.resolve()),
    ]


def _run_case(run: dict[str, object], args: argparse.Namespace) -> dict[str, object]:
    run_id = str(run["run_id"])
    out_dir = args.out_dir / run_id / "spine"
    out_dir.mkdir(parents=True, exist_ok=True)
    command = _command(run, args, out_dir)
    summary_path = out_dir / "summary.json"
    started = time.monotonic()
    if not (args.resume and summary_path.is_file()):
        completed = subprocess.run(
            command,
            cwd=ROOT,
            check=False,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            timeout=args.timeout_seconds,
        )
        (out_dir / "parent_driver.log").write_text(
            completed.stdout, encoding="utf-8"
        )
        if completed.returncode != 0:
            raise RuntimeError(f"{run_id}: cold child failed with rc={completed.returncode}")
    driver_case_seconds = time.monotonic() - started
    cold = _restore_final_values(
        out_dir, json.loads(summary_path.read_text(encoding="utf-8"))
    )
    dynamic_path = args.dynamic_dir / run_id / "spine" / "summary.json"
    dynamic = json.loads(dynamic_path.read_text(encoding="utf-8"))
    problems = _validate_cold_prefix(cold, dynamic)
    dram = aggregate_dram_stats(out_dir / "dram")
    if int(dram["requests"]) != int(cold["backend_requests"]):
        problems.append("dram_request_ledger")
    binding = cold.get("sst_library_binding")
    if not isinstance(binding, dict) or binding.get("plugin_sha256") != cold.get(
        "sst_plugin_sha256"
    ):
        problems.append("plugin_binding")
    if problems:
        raise RuntimeError(f"{run_id}: cold-prefix mismatch: {sorted(set(problems))}")
    return {
        "run_id": run_id,
        "dataset_id": run["dataset_id"],
        "cycles": cold["cycles"],
        "backend_requests": cold["backend_requests"],
        "dram_reads": dram["reads"],
        "dram_writes": dram["writes"],
        "rounds": cold["rounds"],
        "plugin_sha256": cold["sst_plugin_sha256"],
        "summary_sha256": sha256_file(summary_path),
        "dynamic_summary_sha256": sha256_file(dynamic_path),
        "sst_host_wall_seconds": float(cold["sst_host_wall_seconds"]),
        "driver_case_seconds": driver_case_seconds,
        "exact_dynamic_prefix_match": True,
    }


def _write_csv(path: Path, rows: list[dict[str, object]]) -> None:
    with path.open("w", encoding="utf-8", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=list(rows[0]), lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input-manifest", type=Path, default=DEFAULT_MANIFEST)
    parser.add_argument("--dynamic-dir", type=Path, required=True)
    parser.add_argument("--out-dir", type=Path, required=True)
    parser.add_argument("--profile", type=Path, default=DEFAULT_PROFILE)
    parser.add_argument("--sst", type=Path, default=DEFAULT_SST)
    parser.add_argument("--lib-dir", type=Path, default=ROOT / "build/sst-stalls")
    parser.add_argument("--python", default=sys.executable)
    parser.add_argument("--jobs", type=int, default=4)
    parser.add_argument("--timeout-seconds", type=float, default=1200.0)
    parser.add_argument("--max-cycles", type=int, default=100_000_000)
    parser.add_argument("--resume", action="store_true")
    parser.add_argument("--no-build", action="store_true")
    args = parser.parse_args()
    args.dynamic_dir = args.dynamic_dir.resolve()
    args.out_dir = args.out_dir.resolve()
    if args.jobs <= 0 or args.timeout_seconds <= 0 or args.max_cycles <= 0:
        raise ValueError("jobs, timeout, and max cycles must be positive")
    manifest = json.loads(args.input_manifest.read_text(encoding="utf-8"))
    runs = [
        run
        for run in manifest["runs"]
        if run["scenario"] == "insert" and int(run["batch_size"]) == 8
    ]
    if len(runs) != 5:
        raise ValueError("cold matrix requires five insert-u8 temporal runs")
    if not args.no_build:
        subprocess.run(
            ["make", "-C", "cpp/sst", "BUILD_DIR=../../build/sst-stalls", "-j4"],
            cwd=ROOT,
            check=True,
        )
    args.out_dir.mkdir(parents=True, exist_ok=True)
    started = time.monotonic()
    rows: list[dict[str, object]] = []
    with ThreadPoolExecutor(max_workers=args.jobs) as executor:
        futures = {executor.submit(_run_case, run, args): run for run in runs}
        for future in as_completed(futures):
            row = future.result()
            rows.append(row)
            print(
                f"PASS {row['run_id']}: cycles={row['cycles']} "
                f"requests={row['backend_requests']}"
            )
    rows.sort(key=lambda row: str(row["run_id"]))
    rows_path = args.out_dir / "cold_baseline_rows.csv"
    _write_csv(rows_path, rows)
    plugin_shas = {str(row["plugin_sha256"]) for row in rows}
    if len(plugin_shas) != 1:
        raise ValueError("cold matrix used multiple SST plugin builds")
    report = {
        "schema_version": 1,
        "matrix_id": "candidate10_spine_weighted_cold_baselines_v1_20260727",
        "status": "PASS",
        "runs": len(rows),
        "all_exact_dynamic_prefix_matches": True,
        "quiescent_boundary_contract": "spine_idle_and_backend_outstanding_zero",
        "input_manifest_sha256": sha256_file(args.input_manifest),
        "dynamic_dir": str(args.dynamic_dir),
        "profile_sha256": sha256_file(args.profile),
        "sst_sha256": sha256_file(args.sst),
        "plugin_sha256": next(iter(plugin_shas)),
        "cold_baseline_rows_sha256": sha256_file(rows_path),
        "driver_wall_seconds": time.monotonic() - started,
        "sum_child_sst_host_wall_seconds": sum(
            float(row["sst_host_wall_seconds"]) for row in rows
        ),
        "max_child_sst_host_wall_seconds": max(
            float(row["sst_host_wall_seconds"]) for row in rows
        ),
        "execution_fingerprint": hashlib.sha256(
            b"".join(
                path.resolve().read_bytes()
                for path in (
                    Path(__file__),
                    ROOT / "scripts/run_sst_spine_vertical.py",
                    args.profile,
                    args.lib_dir / "libspine_cycle.so",
                )
            )
        ).hexdigest(),
    }
    (args.out_dir / "matrix_manifest.json").write_text(
        json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    print(
        f"PASS weighted cold matrix: runs={len(rows)} "
        f"driver_wall_s={report['driver_wall_seconds']:.3f} "
        f"max_child_wall_s={report['max_child_sst_host_wall_seconds']:.3f}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
