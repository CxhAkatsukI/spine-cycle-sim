#!/usr/bin/env python3
"""Build auditable device-cycle lower bounds from stopped campaign prefixes."""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import math
from pathlib import Path
from typing import Any


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _load_spine_cycles(path: Path) -> dict[tuple[str, str], dict[str, str]]:
    with path.open(encoding="ascii", newline="") as stream:
        rows = list(csv.DictReader(stream))
    selected: dict[tuple[str, str], dict[str, str]] = {}
    for row in rows:
        if (
            row.get("system") == "spine"
            and row.get("scenario") == "insert"
            and row.get("batch_size") == "8"
            and float(row.get("cycles", 0)) > 0
        ):
            selected[(row["dataset_id"], row["algorithm"])] = row
    return selected


def collect_lower_bounds(
    campaign_states: list[Path],
    system_rows_path: Path,
    *,
    thresholds: tuple[float, ...] = (5.0, 100.0),
) -> dict[str, Any]:
    if not thresholds or any(
        not math.isfinite(value) or value <= 1.0 for value in thresholds
    ):
        raise ValueError("lower-bound thresholds must be finite and greater than one")
    ordered_thresholds = tuple(sorted(set(thresholds)))
    spine_rows = _load_spine_cycles(system_rows_path)
    bounds: list[dict[str, Any]] = []
    state_sources: list[dict[str, str]] = []
    seen: set[tuple[str, str]] = set()
    for state_path in campaign_states:
        state = json.loads(state_path.read_text(encoding="ascii"))
        state_sources.append(
            {
                "path": str(state_path.resolve()),
                "sha256": _sha256(state_path),
                "campaign_id": str(state.get("campaign_id", "")),
                "manifest_sha256": str(state.get("manifest_sha256", "")),
            }
        )
        for job in state.get("jobs", []):
            if (
                job.get("status") != "stopped"
                or not str(job.get("system", "")).startswith("grasu_regraph")
            ):
                continue
            progress = job.get("progress")
            if not isinstance(progress, dict) or progress.get("status") != "running":
                continue
            current_cycles = int(progress.get("simulated_cycles", 0))
            if current_cycles <= 0:
                continue
            key = (str(job.get("dataset_id", "")), str(job.get("algorithm", "")))
            if key in seen:
                raise ValueError(f"duplicate stopped-prefix lower bound: {key}")
            spine = spine_rows.get(key)
            if spine is None:
                raise ValueError(f"stopped prefix lacks measured Spine denominator: {key}")
            spine_cycles = int(float(spine["cycles"]))
            ratio = current_cycles / spine_cycles
            certified = [value for value in ordered_thresholds if ratio >= value]
            if not certified:
                continue
            seen.add(key)
            bounds.append(
                {
                    "dataset_id": key[0],
                    "algorithm": key[1],
                    "scenario": "insert",
                    "batch_size": 8,
                    "system": str(job["system"]),
                    "job_id": str(job["job_id"]),
                    "spine_execution_id": str(spine["execution_id"]),
                    "spine_cycles": spine_cycles,
                    "observed_partial_cycles": current_cycles,
                    "strict_lower_bound_ratio": ratio,
                    "certified_threshold": certified[-1],
                    "elapsed_seconds": float(job.get("elapsed_seconds", 0.0)),
                    "backend_requests": int(progress.get("backend_requests", 0)),
                    "peak_rss_bytes": int(job.get("peak_rss_bytes", 0)),
                    "stop_reason": str(job.get("reason", "")),
                    "claim_class": (
                        "strict_monotonic_device_cycle_lower_bound_from_"
                        "stopped_incomplete_execution"
                    ),
                    "admitted_as_completed_performance": False,
                }
            )
    bounds.sort(key=lambda row: (row["algorithm"], row["dataset_id"]))
    return {
        "schema_version": 1,
        "evidence_id": "formal_v7_stopped_prefix_lower_bounds_v1_20260731",
        "system_rows": {
            "path": str(system_rows_path.resolve()),
            "sha256": _sha256(system_rows_path),
        },
        "campaign_states": state_sources,
        "thresholds": list(ordered_thresholds),
        "lower_bounds": bounds,
        "claim_boundary": (
            "Each row is a strict lower bound from monotonically increasing device "
            "cycles in an incomplete execution. It is neither a completed result nor "
            "a projected total and is excluded from matched-pair aggregates."
        ),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--campaign-state", type=Path, action="append", required=True)
    parser.add_argument("--system-rows", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    evidence = collect_lower_bounds(args.campaign_state, args.system_rows)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(
        json.dumps(evidence, indent=2, sort_keys=True) + "\n", encoding="ascii"
    )
    print(
        f"PASS stopped-prefix lower bounds: {len(evidence['lower_bounds'])} rows"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
