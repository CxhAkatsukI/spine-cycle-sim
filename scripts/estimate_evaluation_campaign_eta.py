#!/usr/bin/env python3
"""Estimate remaining time for the evaluation-refresh calibration campaign."""

from __future__ import annotations

import argparse
import csv
import json
import statistics
import time
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_RUN_DIR = Path("/data/tmp/chuxiao/evaluation_refresh_20260810_calibration_frozen/run")
DEFAULT_REFERENCE = ROOT / "docs" / "paper" / "data" / "formal_v7_primary" / "pairs.csv"


def read_csv(path: Path) -> list[dict[str, str]]:
    with path.open(newline="", encoding="utf-8") as source:
        return list(csv.DictReader(source))


def load_reference_cycles(path: Path) -> dict[tuple[str, str, str], float]:
    reference: dict[tuple[str, str, str], float] = {}
    if not path.is_file():
        return reference
    for row in read_csv(path):
        dataset = row.get("dataset_id", "")
        algorithm = row.get("algorithm", "")
        competitor = row.get("competitor", "")
        if competitor != "grasu_regraph_k4_shared":
            continue
        if row.get("spine_cycles"):
            reference[(dataset, algorithm, "spine")] = float(row["spine_cycles"])
        if row.get("k4_cycles"):
            reference[(dataset, algorithm, "grasu_regraph_k4_shared")] = float(row["k4_cycles"])
    return reference


def current_cycles(job: dict[str, Any]) -> float | None:
    progress = job.get("progress")
    if not isinstance(progress, dict):
        return None
    value = progress.get("simulated_cycles")
    if value is None:
        return None
    return float(value)


def fmt_seconds(seconds: float | None) -> str:
    if seconds is None:
        return "-"
    if seconds < 0:
        seconds = 0.0
    minutes, sec = divmod(int(seconds), 60)
    hours, minutes = divmod(minutes, 60)
    if hours:
        return f"{hours:d}h{minutes:02d}m"
    return f"{minutes:d}m{sec:02d}s"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run-dir", type=Path, default=DEFAULT_RUN_DIR)
    parser.add_argument("--reference", type=Path, default=DEFAULT_REFERENCE)
    args = parser.parse_args()

    state_path = args.run_dir / "campaign_state.json"
    state = json.loads(state_path.read_text(encoding="ascii"))
    reference = load_reference_cycles(args.reference)
    now = time.time()

    rates_by_system: dict[str, list[float]] = {}
    rows = []
    for job in state["jobs"]:
        status = job["status"]
        system = job["system"]
        dataset = job["dataset_id"]
        algorithm = job["algorithm"]
        target = reference.get((dataset, algorithm, system))
        cycles = current_cycles(job)
        elapsed = float(job.get("elapsed_seconds") or 0.0)
        rate = cycles / elapsed if cycles is not None and elapsed > 0 else None
        if status == "running" and rate and rate > 0:
            rates_by_system.setdefault(system, []).append(rate)
        if status in {"running", "queued"}:
            rows.append((job, target, cycles, elapsed, rate))

    median_rate = {
        system: statistics.median(values)
        for system, values in rates_by_system.items()
        if values
    }
    counts: dict[str, int] = {}
    for job in state["jobs"]:
        counts[str(job["status"])] = counts.get(str(job["status"]), 0) + 1
    print(
        f"Campaign {state['status']} pass={counts.get('pass', 0)} "
        f"run={counts.get('running', 0)} queue={counts.get('queued', 0)} "
        f"fail={counts.get('fail', 0)}"
    )
    print("STATUS    DATASET        ALGORITHM                    SYSTEM               CYCLES/TARGET       RATE(cyc/s)  ETA")
    total_remaining = 0.0
    total_known = True
    for job, target, cycles, elapsed, rate in rows:
        system = job["system"]
        effective_rate = rate or median_rate.get(system)
        eta = None
        if target and effective_rate and effective_rate > 0:
            done = cycles or 0.0
            eta = max(0.0, (target - done) / effective_rate)
            total_remaining += eta
        elif job["status"] != "queued":
            total_known = False
        current = "-" if cycles is None else f"{cycles/1e6:.1f}M"
        target_text = "-" if target is None else f"{target/1e6:.1f}M"
        rate_text = "-" if effective_rate is None else f"{effective_rate:,.0f}"
        print(
            f"{job['status']:<9} {job['dataset_id'][:13]:<13} "
            f"{job['algorithm'][:28]:<28} {system[:20]:<20} "
            f"{current:>7}/{target_text:<7} {rate_text:>11}  {fmt_seconds(eta)}"
        )
    if rows and total_known:
        print(f"Known serial ETA sum for listed work: {fmt_seconds(total_remaining)}")
    print(f"state_updated_seconds_ago={now - float(state.get('updated_at', now)):.1f}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
