#!/usr/bin/env python3
"""Run and validate the real Spine vertical slice on SST-HBM."""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import subprocess
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_SST = Path("/data/feiyang/sst/bin/sst")
DEFAULT_WORKLOAD = ROOT / "tests" / "data" / "amazon_top1_exact.slice"


def collect_dram_stats(out_dir: Path) -> dict[str, int | float]:
    totals: dict[str, int | float] = {
        "dram_channels": 0,
        "dram_reads": 0,
        "dram_writes": 0,
        "dram_activates": 0,
        "dram_precharges": 0,
        "dram_read_row_hits": 0,
        "dram_write_row_hits": 0,
        "dram_total_energy_pj": 0.0,
    }
    paths = sorted((out_dir / "dram").glob("channel*/dramsim3.json"))
    if not paths:
        raise ValueError(f"no DRAMSim3 JSON found under {out_dir / 'dram'}")
    for path in paths:
        payload = json.loads(path.read_text(encoding="utf-8"))
        if len(payload) != 1:
            raise ValueError(f"expected one DRAM record in {path}")
        row = next(iter(payload.values()))
        totals["dram_channels"] += 1
        totals["dram_reads"] += int(row["num_reads_done"])
        totals["dram_writes"] += int(row["num_writes_done"])
        totals["dram_activates"] += int(row["num_act_cmds"])
        totals["dram_precharges"] += int(row["num_pre_cmds"])
        totals["dram_read_row_hits"] += int(row["num_read_row_hits"])
        totals["dram_write_row_hits"] += int(row["num_write_row_hits"])
        totals["dram_total_energy_pj"] += float(row["total_energy"])
    return totals


def validate_result(
    result: dict[str, Any], dram: dict[str, int | float], *, channels: int
) -> list[str]:
    checks = {
        "success": result.get("success") is True,
        "mode": result.get("mode") == "spine_vertical",
        "correctness": result.get("correctness_mismatches") == 0,
        "frontier_correctness": result.get("frontier_mismatches") == 0,
        "frontier": result.get("next_active") == 10,
        "maintenance_passes": result.get("maintenance_scan_passes") == 19,
        "maintenance_visits": result.get("maintenance_edge_visits") == 190,
        "maintenance_bytes": result.get("maintenance_sorted_bytes") == 3_040,
        "reader_tiles": result.get("reader_tiles") == 5,
        "reader_edges": result.get("reader_edges") == 10,
        "reader_bytes": result.get("reader_graph_bytes") == 224,
        "compute_fast_tiles": result.get("compute_fast_tiles") == 5,
        "compute_no_full_tiles": result.get("compute_full_tiles") == 0,
        "compute_edges": result.get("compute_processed_edges") == 10,
        "axis_transfers": result.get("edge_axis_transfers") == 22,
        "axis_capacity": 0 <= result.get("edge_axis_max_occupancy", -1) <= 32,
        "dram_matches_backend": int(dram.get("dram_reads", 0))
        + int(dram.get("dram_writes", 0))
        == result.get("backend_requests"),
        "channel_count": dram.get("dram_channels") == channels,
    }
    return [name for name, passed in checks.items() if not passed]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out-dir", type=Path, required=True)
    parser.add_argument("--sst", type=Path, default=DEFAULT_SST)
    parser.add_argument("--lib-dir", type=Path, default=ROOT / "build" / "sst")
    parser.add_argument("--workload", type=Path, default=DEFAULT_WORKLOAD)
    parser.add_argument("--source", type=int, default=2)
    parser.add_argument("--channels", type=int, default=32)
    parser.add_argument("--no-build", action="store_true")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    if args.channels < 23 or args.source < 0 or not args.workload.is_file():
        raise SystemExit("channels must be >=23, source non-negative, workload present")
    if not args.no_build:
        subprocess.run(["make", "-C", "cpp/sst"], cwd=ROOT, check=True)
    library = args.lib_dir / "libspine_cycle.so"
    if not library.is_file():
        raise SystemExit(f"missing SST element library: {library}")
    args.out_dir.mkdir(parents=True, exist_ok=True)
    result_path = args.out_dir / "result.json"
    env = os.environ.copy()
    env.update(
        {
            "SPINE_SST_CHANNELS": str(args.channels),
            "SPINE_SST_WORKLOAD": str(args.workload.resolve()),
            "SPINE_SST_SOURCE": str(args.source),
            "SPINE_SST_OUTPUT": str(result_path),
            "SPINE_SST_DRAM_OUTPUT": str(args.out_dir / "dram"),
        }
    )
    command = [
        str(args.sst),
        f"--add-lib-path={args.lib_dir}",
        str(ROOT / "sst" / "spine_vertical_slice.py"),
    ]
    completed = subprocess.run(
        command,
        cwd=ROOT,
        env=env,
        check=False,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
    )
    (args.out_dir / "sst.log").write_text(completed.stdout, encoding="utf-8")
    if completed.returncode != 0:
        raise RuntimeError(
            f"SST Spine vertical slice failed with rc={completed.returncode}; "
            f"see {args.out_dir / 'sst.log'}"
        )
    result = json.loads(result_path.read_text(encoding="utf-8"))
    dram = collect_dram_stats(args.out_dir)
    problems = validate_result(result, dram, channels=args.channels)
    if problems:
        raise RuntimeError(f"SST Spine checks failed: {', '.join(problems)}")
    summary = {**result, **dram, "status": "PASS"}
    (args.out_dir / "summary.json").write_text(
        json.dumps(summary, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    print(
        f"PASS spine_vertical: cycles={result['cycles']} "
        f"backend_requests={result['backend_requests']} "
        f"DRAM={int(dram['dram_reads']) + int(dram['dram_writes'])} "
        f"ACT={dram['dram_activates']} row_hits="
        f"{int(dram['dram_read_row_hits']) + int(dram['dram_write_row_hits'])}"
    )
    print(f"evidence: {args.out_dir}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
