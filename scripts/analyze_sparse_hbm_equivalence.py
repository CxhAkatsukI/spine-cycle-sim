#!/usr/bin/env python3
"""Verify full-vs-sparse SST HBM controller equivalence evidence."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def load_run(path: Path) -> tuple[dict[str, Any], dict[str, Any], float]:
    summary_path = path / "summary.json"
    manifest_path = path / "manifest.json"
    if summary_path.is_file():
        payload = json.loads(summary_path.read_text(encoding="utf-8"))
        binding = dict(payload["sst_memory_binding"])
        wall_seconds = float(payload["sst_host_wall_seconds"])
    elif manifest_path.is_file():
        payload = json.loads(manifest_path.read_text(encoding="utf-8"))
        binding = dict(payload["sst_memory_binding"])
        wall_seconds = float(payload["sst_host_wall_seconds"])
    else:
        raise ValueError(f"missing child summary or manifest under {path}")
    return payload, binding, wall_seconds


def channel_directories(path: Path) -> tuple[int, ...]:
    channels: list[int] = []
    for child in (path / "dram").glob("channel*"):
        if child.is_dir():
            channels.append(int(child.name.removeprefix("channel")))
    return tuple(sorted(channels))


def compare_case(name: str, full_dir: Path, sparse_dir: Path) -> dict[str, Any]:
    full_payload, full_binding, full_wall = load_run(full_dir)
    sparse_payload, sparse_binding, sparse_wall = load_run(sparse_dir)
    physical_channels = int(full_binding["physical_channels"])
    full_channels = tuple(int(value) for value in full_binding["instantiated_channels"])
    sparse_channels = tuple(
        int(value) for value in sparse_binding["instantiated_channels"]
    )
    expected_full = tuple(range(physical_channels))
    checks = {
        "same_physical_namespace": sparse_binding["physical_channels"]
        == physical_channels,
        "full_instantiates_physical_namespace": full_channels == expected_full,
        "sparse_instantiates_reachable_set": sparse_channels
        == tuple(int(value) for value in sparse_binding["reachable_channels"]),
        "full_directories": channel_directories(full_dir) == expected_full,
        "sparse_directories": channel_directories(sparse_dir) == sparse_channels,
        "fail_closed": full_binding["unbound_request_policy"] == "fatal"
        and sparse_binding["unbound_request_policy"] == "fatal",
        "channel_numbers_preserved": full_binding["channel_numbers_preserved"] is True
        and sparse_binding["channel_numbers_preserved"] is True,
    }
    result_full = full_dir / "result.json"
    result_sparse = sparse_dir / "result.json"
    full_result_sha = sha256(result_full)
    sparse_result_sha = sha256(result_sparse)
    checks["result_byte_identity"] = full_result_sha == sparse_result_sha

    active_files: dict[str, str] = {}
    for channel in sparse_channels:
        for filename in ("dramsim3.json", "dramsim3.txt"):
            relative = f"channel{channel}/{filename}"
            full_path = full_dir / "dram" / relative
            sparse_path = sparse_dir / "dram" / relative
            if not full_path.is_file() or not sparse_path.is_file():
                checks[f"active_file:{relative}"] = False
                continue
            full_sha = sha256(full_path)
            sparse_sha = sha256(sparse_path)
            checks[f"active_file:{relative}"] = full_sha == sparse_sha
            if full_sha == sparse_sha:
                active_files[relative] = full_sha

    failed = sorted(key for key, passed in checks.items() if not passed)
    if failed:
        raise RuntimeError(f"{name}: sparse HBM equivalence failed: {failed}")
    result = json.loads(result_full.read_text(encoding="utf-8"))
    return {
        "case": name,
        "physical_hbm_channels": physical_channels,
        "sparse_instantiated_channels": list(sparse_channels),
        "omitted_idle_controllers": physical_channels - len(sparse_channels),
        "cycles": result["cycles"],
        "backend_requests": result["backend_requests"],
        "correctness_mismatches": result.get("correctness_mismatches"),
        "result_sha256": full_result_sha,
        "active_dramsim_outputs_byte_identical": True,
        "active_dramsim_sha256": active_files,
        "full_sst_host_wall_seconds": full_wall,
        "sparse_sst_host_wall_seconds": sparse_wall,
        "host_runtime_speedup": full_wall / sparse_wall,
        "host_runtime_reduction_pct": (1.0 - sparse_wall / full_wall) * 100.0,
        "status": "PASS_EXACT_EQUIVALENCE",
    }


def parse_case(text: str) -> tuple[str, Path, Path]:
    fields = text.split("=", 1)
    if len(fields) != 2 or not fields[0]:
        raise argparse.ArgumentTypeError("case must be NAME=FULL_DIR,SPARSE_DIR")
    paths = fields[1].split(",")
    if len(paths) != 2:
        raise argparse.ArgumentTypeError("case must be NAME=FULL_DIR,SPARSE_DIR")
    return fields[0], Path(paths[0]).resolve(), Path(paths[1]).resolve()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--case", action="append", type=parse_case, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    cases = [compare_case(name, full, sparse) for name, full, sparse in args.case]
    output = {
        "schema_version": 1,
        "claim_class": "simulator_host_runtime_only_exact_timing_equivalence",
        "architecture_semantics": (
            "32_physical_channels_with_unmodified_active_channel_contention"
        ),
        "energy_boundary": (
            "sparse_runs_exclude_unbound_channel_idle_and_background_energy"
        ),
        "cases": cases,
        "status": "PASS" if cases else "FAIL",
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(output, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    print(f"PASS sparse HBM equivalence: cases={len(cases)} output={args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
