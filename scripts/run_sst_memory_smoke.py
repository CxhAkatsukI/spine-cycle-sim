#!/usr/bin/env python3
"""Build and validate the online AXI -> SST -> DRAMSim3 memory path."""

from __future__ import annotations

import argparse
import csv
from dataclasses import asdict, dataclass
import json
import os
from pathlib import Path
import subprocess
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_SST = Path("/data/feiyang/sst/bin/sst")


@dataclass(frozen=True)
class SmokeCase:
    name: str
    stride_bytes: int
    write_percent: int


CASES = (
    SmokeCase("sequential_read", stride_bytes=64, write_percent=0),
    SmokeCase("cross_row_read", stride_bytes=131_072, write_percent=0),
    SmokeCase("mixed_read_write", stride_bytes=4_096, write_percent=50),
)


def _channel_stats(case_dir: Path) -> dict[str, float]:
    totals: dict[str, float] = {
        "dram_channels": 0,
        "dram_reads": 0,
        "dram_writes": 0,
        "dram_activates": 0,
        "dram_precharges": 0,
        "dram_read_row_hits": 0,
        "dram_write_row_hits": 0,
        "dram_total_energy_pj": 0.0,
    }
    paths = sorted((case_dir / "dram").glob("channel*/dramsim3.json"))
    if not paths:
        raise ValueError(f"no DRAMSim3 JSON found under {case_dir / 'dram'}")
    for path in paths:
        payload = json.loads(path.read_text(encoding="utf-8"))
        if len(payload) != 1:
            raise ValueError(f"expected one DRAM channel record in {path}")
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


def validate_case(
    result: dict[str, Any], dram: dict[str, float], *, requests: int,
    request_bytes: int, channels: int
) -> list[str]:
    problems: list[str] = []
    expected_bytes = requests * request_bytes
    checks = {
        "success": result.get("success") is True,
        "requests_issued": result.get("requests_issued") == requests,
        "requests_completed": result.get("requests_completed") == requests,
        "requests_failed": result.get("requests_failed") == 0,
        "backend_matches_axi": result.get("backend_requests")
        == result.get("axi_beats"),
        "bytes_match_input": result.get("axi_read_bytes", 0)
        + result.get("axi_write_bytes", 0)
        == expected_bytes,
        "dram_matches_backend": dram.get("dram_reads", 0)
        + dram.get("dram_writes", 0)
        == result.get("backend_requests"),
        "channel_count": dram.get("dram_channels") == channels,
    }
    for name, passed in checks.items():
        if not passed:
            problems.append(name)
    return problems


def run_case(
    case: SmokeCase,
    *,
    out_dir: Path,
    sst: Path,
    lib_dir: Path,
    requests: int,
    request_bytes: int,
    channels: int,
) -> dict[str, Any]:
    case_dir = out_dir / case.name
    case_dir.mkdir(parents=True, exist_ok=True)
    result_path = case_dir / "result.json"
    env = os.environ.copy()
    env.update(
        {
            "SPINE_SST_CHANNELS": str(channels),
            "SPINE_SST_REQUESTS": str(requests),
            "SPINE_SST_REQUEST_BYTES": str(request_bytes),
            "SPINE_SST_STRIDE_BYTES": str(case.stride_bytes),
            "SPINE_SST_WRITE_PERCENT": str(case.write_percent),
            "SPINE_SST_OUTPUT": str(result_path),
            "SPINE_SST_DRAM_OUTPUT": str(case_dir / "dram"),
        }
    )
    command = [
        str(sst),
        f"--add-lib-path={lib_dir}",
        str(ROOT / "sst" / "online_memory_probe.py"),
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
    (case_dir / "sst.log").write_text(completed.stdout, encoding="utf-8")
    if completed.returncode != 0:
        raise RuntimeError(
            f"SST case {case.name} failed with rc={completed.returncode}; "
            f"see {case_dir / 'sst.log'}"
        )
    result = json.loads(result_path.read_text(encoding="utf-8"))
    dram = _channel_stats(case_dir)
    problems = validate_case(
        result,
        dram,
        requests=requests,
        request_bytes=request_bytes,
        channels=channels,
    )
    if problems:
        raise RuntimeError(f"SST case {case.name} failed checks: {', '.join(problems)}")
    return {**asdict(case), **result, **dram, "status": "PASS"}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out-dir", type=Path, required=True)
    parser.add_argument("--sst", type=Path, default=DEFAULT_SST)
    parser.add_argument("--lib-dir", type=Path, default=ROOT / "build" / "sst")
    parser.add_argument("--requests", type=int, default=64)
    parser.add_argument("--request-bytes", type=int, default=64)
    parser.add_argument("--channels", type=int, default=1)
    parser.add_argument("--no-build", action="store_true")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    if args.requests <= 0 or args.request_bytes <= 0 or args.channels <= 0:
        raise SystemExit("requests, request-bytes, and channels must be positive")
    if not args.no_build:
        subprocess.run(["make", "-C", "cpp/sst"], cwd=ROOT, check=True)
    library = args.lib_dir / "libspine_cycle.so"
    if not library.is_file():
        raise SystemExit(f"missing SST element library: {library}")
    args.out_dir.mkdir(parents=True, exist_ok=True)

    rows = [
        run_case(
            case,
            out_dir=args.out_dir,
            sst=args.sst,
            lib_dir=args.lib_dir,
            requests=args.requests,
            request_bytes=args.request_bytes,
            channels=args.channels,
        )
        for case in CASES
    ]
    by_name = {row["name"]: row for row in rows}
    sequential = by_name["sequential_read"]
    cross_row = by_name["cross_row_read"]
    if cross_row["dram_activates"] <= sequential["dram_activates"]:
        raise RuntimeError("cross-row case did not increase DRAM ACT commands")
    if cross_row["dram_read_row_hits"] >= sequential["dram_read_row_hits"]:
        raise RuntimeError("cross-row case did not reduce DRAM row hits")
    if cross_row["cycles"] <= sequential["cycles"]:
        raise RuntimeError("cross-row case did not increase simulated core cycles")

    (args.out_dir / "summary.json").write_text(
        json.dumps(rows, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    fieldnames = list(rows[0])
    with (args.out_dir / "summary.csv").open("w", newline="", encoding="utf-8") as out:
        writer = csv.DictWriter(out, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)
    for row in rows:
        print(
            f"PASS {row['name']}: cycles={row['cycles']} "
            f"dram_requests={int(row['dram_reads'] + row['dram_writes'])} "
            f"ACT={int(row['dram_activates'])} "
            f"row_hits={int(row['dram_read_row_hits'] + row['dram_write_row_hits'])}"
        )
    print(f"evidence: {args.out_dir}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
