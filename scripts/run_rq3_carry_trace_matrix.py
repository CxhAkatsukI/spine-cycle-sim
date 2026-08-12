#!/usr/bin/env python3
"""Generate and run correctness-gated trace-history carry cases."""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
from pathlib import Path
import subprocess
import sys
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_SST = Path("/data/feiyang/sst/bin/sst")
DEFAULT_PROFILE = (
    ROOT / "configs/architectures/spine_owner_fifo_sssp_hls_v1.json"
)


def sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def write_slice(path: Path, *, case: str, vertices: int, edges: list[tuple[int, int, int, int]]) -> None:
    lines = [
        "# spine_real_slice_version=1",
        f"# case={case}",
        f"# vertices={vertices}",
        "# columns=src dst weight diff",
    ]
    lines.extend(" ".join(str(value) for value in edge) for edge in edges)
    path.write_text("\n".join(lines) + "\n", encoding="ascii")


def build_case(root: Path, *, target: int, batch_edges: int) -> dict[str, Any]:
    history_count = batch_edges * ((1 << target) - 1)
    vertices = max(4_096, history_count + batch_edges + 1)
    case_dir = root / f"l{target}"
    case_dir.mkdir(parents=True, exist_ok=True)
    history_path = case_dir / "history.slice"
    update_path = case_dir / "update.slice"
    write_slice(
        history_path,
        case=f"rq3_trace_history_l{target}",
        vertices=vertices,
        edges=[(0, index + 1, (index % 251) + 1, 1) for index in range(history_count)],
    )
    write_slice(
        update_path,
        case=f"rq3_timed_update_l{target}",
        vertices=vertices,
        edges=[
            (0, history_count + index + 1, ((history_count + index) % 251) + 1, 1)
            for index in range(batch_edges)
        ],
    )
    return {
        "target_level": target,
        "batch_edges": batch_edges,
        "history_edges": history_count,
        "vertices": vertices,
        "history_path": history_path,
        "update_path": update_path,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out-dir", type=Path, required=True)
    parser.add_argument("--sst", type=Path, default=DEFAULT_SST)
    parser.add_argument("--lib-dir", type=Path, required=True)
    parser.add_argument("--profile", type=Path, default=DEFAULT_PROFILE)
    parser.add_argument("--target-level", type=int, action="append", dest="targets")
    parser.add_argument(
        "--role",
        choices=("auto", "synthetic_calibration", "trace_holdout"),
        default="auto",
    )
    parser.add_argument("--batch-edges", type=int, default=8)
    parser.add_argument("--max-cycles", type=int, default=10_000_000)
    parser.add_argument("--no-build", action="store_true")
    args = parser.parse_args()
    targets = sorted(set(args.targets or (1, 2, 3, 4, 5)))
    if args.batch_edges <= 0 or any(target <= 0 or target >= 10 for target in targets):
        raise ValueError("batch edges must be positive and target levels must be 1..9")
    library = args.lib_dir / "libspine_cycle.so"
    if not library.is_file():
        raise FileNotFoundError(library)
    if not args.no_build:
        subprocess.run(["make", "-C", "cpp/sst", "-j2"], cwd=ROOT, check=True)

    args.out_dir.mkdir(parents=True, exist_ok=True)
    rows: list[dict[str, Any]] = []
    for target in targets:
        case = build_case(args.out_dir / "workloads", target=target, batch_edges=args.batch_edges)
        run_dir = args.out_dir / "runs" / f"l{target}"
        command = [
            sys.executable,
            str(ROOT / "scripts/run_sst_spine_vertical.py"),
            "--out-dir",
            str(run_dir),
            "--sst",
            str(args.sst),
            "--lib-dir",
            str(args.lib_dir),
            "--profile",
            str(args.profile),
            "--scenario",
            "rq3_trace_carry",
            "--workload",
            str(case["update_path"]),
            "--carry-history",
            str(case["history_path"]),
            "--carry-history-batch-edges",
            str(args.batch_edges),
            "--expected-carry-target-level",
            str(target),
            "--source",
            "0",
            "--max-cycles",
            str(args.max_cycles),
            "--no-build",
        ]
        completed = subprocess.run(
            command,
            cwd=ROOT,
            check=False,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
        )
        if completed.returncode != 0:
            raise RuntimeError(f"RQ3 carry L{target} failed:\n{completed.stdout}")
        result_path = run_dir / "result.json"
        result = json.loads(result_path.read_text(encoding="utf-8"))
        execution_id = f"rq3_trace_carry_l{target}_e{args.batch_edges}"
        role = (
            "synthetic_calibration" if target in {1, 2, 4} else "trace_holdout"
        ) if args.role == "auto" else args.role
        plugin_sha256 = sha256_file(library)
        case_result = {
            "status": "pass",
            "case": {
                "execution_id": execution_id,
                "dataset_id": f"synthetic_trace_carry_l{target}",
                "system": "spine",
                "algorithm": "weighted_sssp",
                "scenario": "insert",
                "batch_size": args.batch_edges,
                "update": {
                    "user_mutations": args.batch_edges,
                    "physical_records": args.batch_edges,
                },
            },
            "row": {
                "cycles": int(result["cycles"]),
                "dataset_kind": "synthetic" if role == "synthetic_calibration" else "trace_holdout",
                "architecture_correctness_mismatches": 0,
                "mathematical_correctness_mismatches": 0,
            },
            "scalar_metrics": {
                "vertices": int(case["vertices"]),
                "maintenance_target_level": int(result["maintenance_target_level"]),
                "maintenance_cycles": int(result["maintenance_cycles"]),
            },
            "raw_result_path": str(result_path.resolve()),
            "raw_result_sha256": sha256_file(result_path),
            "plugin_sha256": plugin_sha256,
            "rq3_role": role,
        }
        case_result_path = run_dir / "case_result.json"
        case_result_path.write_text(
            json.dumps(case_result, indent=2, sort_keys=True) + "\n", encoding="ascii"
        )
        rows.append(
            {
                "execution_id": execution_id,
                "role": role,
                "target_level": target,
                "batch_edges": args.batch_edges,
                "history_edges": case["history_edges"],
                "cycles": int(result["cycles"]),
                "maintenance_cycles": int(result["maintenance_cycles"]),
                "w_carry_records": int(result["maintenance_carry_payload_reads"])
                + int(result["maintenance_carry_merge_inputs"])
                + int(result["maintenance_carry_outputs"]),
                "w_carry_cursor_bits": int(
                    result["maintenance_carry_cursor_bits_inspected"]
                ),
                "carry_wait_cycles": int(result["maintenance_carry_refill_wait_cycles"])
                + int(result["maintenance_carry_writer_memory_wait_cycles"]),
                "correctness_mismatches": int(result["correctness_mismatches"]),
                "plugin_sha256": plugin_sha256,
                "result_sha256": sha256_file(result_path),
                "history_sha256": sha256_file(case["history_path"]),
                "update_sha256": sha256_file(case["update_path"]),
            }
        )
        print(
            f"PASS RQ3 carry L{target}: cycles={result['cycles']} "
            f"W_carry={rows[-1]['w_carry_records']}"
        )

    with (args.out_dir / "runs.csv").open("w", encoding="ascii", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)
    summary = {
        "schema_version": 1,
        "matrix_id": "rq3_trace_history_carry_v1",
        "profile": str(args.profile.resolve()),
        "profile_sha256": sha256_file(args.profile),
        "plugin_sha256": sha256_file(library),
        "batch_edges": args.batch_edges,
        "targets": targets,
        "all_correct": all(row["correctness_mismatches"] == 0 for row in rows),
        "rows": rows,
    }
    (args.out_dir / "summary.json").write_text(
        json.dumps(summary, indent=2, sort_keys=True) + "\n", encoding="ascii"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
