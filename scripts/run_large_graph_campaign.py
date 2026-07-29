#!/usr/bin/env python3
"""Launch a resumable, resource-aware simulator campaign."""

from __future__ import annotations

import argparse
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from spine_cycle_sim.experiments.campaign_runtime import CampaignRunner


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--run-dir", type=Path, required=True)
    parser.add_argument("--jobs", type=int, default=6)
    parser.add_argument("--large-jobs", type=int, default=2)
    parser.add_argument("--memory-reserve-gib", type=float, default=64.0)
    parser.add_argument(
        "--memory-emergency-gib",
        type=float,
        help="soft-stop running jobs below this MemAvailable threshold; defaults to reserve",
    )
    parser.add_argument(
        "--memory-recovery-gib",
        type=float,
        help="resume launching above this threshold; defaults to max(reserve, emergency)",
    )
    parser.add_argument("--max-starts-per-sample", type=int, default=4)
    parser.add_argument("--sample-seconds", type=float, default=5.0)
    parser.add_argument("--no-progress-warn-minutes", type=float, default=20.0)
    parser.add_argument(
        "--cpu-offset",
        type=int,
        default=0,
        help="Start this launcher's deterministic physical-CPU pool at this offset.",
    )
    parser.add_argument("--resume", action="store_true")
    parser.add_argument("--no-pin-cpus", action="store_true")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    runner = CampaignRunner(
        args.manifest,
        args.run_dir,
        jobs=args.jobs,
        large_jobs=args.large_jobs,
        memory_reserve_bytes=int(args.memory_reserve_gib * 2**30),
        memory_emergency_bytes=(
            None
            if args.memory_emergency_gib is None
            else int(args.memory_emergency_gib * 2**30)
        ),
        memory_recovery_bytes=(
            None
            if args.memory_recovery_gib is None
            else int(args.memory_recovery_gib * 2**30)
        ),
        max_starts_per_sample=args.max_starts_per_sample,
        sample_seconds=args.sample_seconds,
        pin_cpus=not args.no_pin_cpus,
        resume=args.resume,
        no_progress_warn_seconds=args.no_progress_warn_minutes * 60.0,
        cpu_offset=args.cpu_offset,
    )
    print(
        "Monitor with:\n"
        f"  watch -n 2 python3 scripts/monitor_large_graph_campaign.py "
        f"--run-dir {args.run_dir.resolve()}",
        flush=True,
    )
    return 0 if runner.run() else 1


if __name__ == "__main__":
    raise SystemExit(main())
