#!/usr/bin/env python3
"""Validate payload-carrying AXI reads/writes on online SST/DRAMSim3."""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import subprocess
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_SST = Path("/data/feiyang/sst/bin/sst")


def collect_dram_commands(out_dir: Path) -> tuple[int, int, int]:
    reads = 0
    writes = 0
    paths = sorted((out_dir / "dram").glob("channel*/dramsim3.json"))
    if not paths:
        raise ValueError("DRAMSim3 did not produce channel evidence")
    for path in paths:
        payload = json.loads(path.read_text(encoding="utf-8"))
        if len(payload) != 1:
            raise ValueError(f"expected one DRAM record in {path}")
        row = next(iter(payload.values()))
        reads += int(row["num_reads_done"])
        writes += int(row["num_writes_done"])
    return reads, writes, len(paths)


def validate_payload_result(
    result: dict[str, Any], *, dram_reads: int, dram_writes: int, channels: int
) -> list[str]:
    checks = {
        "success": result.get("success") is True,
        "mode": result.get("mode") == "payload_roundtrip",
        "payload_bytes": result.get("payload_bytes") == 1600,
        "read_bytes": result.get("axi_read_bytes") == 1600,
        "write_bytes": result.get("axi_write_bytes") == 1600,
        "explicit_write_payload": result.get("zero_filled_write_bytes") == 0,
        "beat_ledger": result.get("axi_beats") == 50,
        "backend_ledger": result.get("backend_requests")
        == result.get("axi_beats"),
        "dram_ledger": dram_reads + dram_writes
        == result.get("backend_requests"),
        "dram_channels": channels > 0,
    }
    return [name for name, passed in checks.items() if not passed]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out-dir", type=Path, required=True)
    parser.add_argument("--sst", type=Path, default=DEFAULT_SST)
    parser.add_argument("--lib-dir", type=Path, default=ROOT / "build" / "sst")
    parser.add_argument("--channels", type=int, default=2)
    parser.add_argument("--no-build", action="store_true")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    if args.channels <= 0:
        raise SystemExit("channels must be positive")
    if not args.no_build:
        subprocess.run(["make", "-C", "cpp/sst", "-j2"], cwd=ROOT, check=True)
    library = args.lib_dir / "libspine_cycle.so"
    if not library.is_file():
        raise SystemExit(f"missing SST element library: {library}")

    args.out_dir.mkdir(parents=True, exist_ok=True)
    result_path = args.out_dir / "result.json"
    env = os.environ.copy()
    env.update(
        {
            "SPINE_SST_MODE": "payload_roundtrip",
            "SPINE_SST_CHANNELS": str(args.channels),
            "SPINE_SST_OUTPUT": str(result_path.resolve()),
            "SPINE_SST_DRAM_OUTPUT": str((args.out_dir / "dram").resolve()),
        }
    )
    command = [
        str(args.sst),
        f"--add-lib-path={args.lib_dir.resolve()}",
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
    (args.out_dir / "sst.log").write_text(completed.stdout, encoding="utf-8")
    if completed.returncode != 0:
        raise RuntimeError(
            f"SST payload round trip failed with rc={completed.returncode}; "
            f"see {args.out_dir / 'sst.log'}"
        )

    result = json.loads(result_path.read_text(encoding="utf-8"))
    dram_reads, dram_writes, dram_channels = collect_dram_commands(args.out_dir)
    problems = validate_payload_result(
        result,
        dram_reads=dram_reads,
        dram_writes=dram_writes,
        channels=dram_channels,
    )
    if problems:
        raise RuntimeError(f"SST payload checks failed: {', '.join(problems)}")
    summary = {
        **result,
        "dram_reads": dram_reads,
        "dram_writes": dram_writes,
        "dram_channels": dram_channels,
        "simulation_evidence_tier": "structural_execution_driven",
        "status": "PASS",
    }
    (args.out_dir / "summary.json").write_text(
        json.dumps(summary, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    print(
        f"PASS payload_roundtrip: cycles={result['cycles']} "
        f"bytes={result['payload_bytes']} backend={result['backend_requests']}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
