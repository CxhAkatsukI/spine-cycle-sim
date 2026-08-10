#!/usr/bin/env python3
"""Request an auditable soft-stop of one campaign job or the whole campaign."""

from __future__ import annotations

import argparse
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from spine_cycle_sim.experiments.campaign_runtime import write_control_request


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run-dir", type=Path, required=True)
    subparsers = parser.add_subparsers(dest="command", required=True)
    stop = subparsers.add_parser("stop", help="soft-stop one job")
    stop.add_argument("job_id")
    stop.add_argument("--reason", required=True)
    stop_all = subparsers.add_parser("stop-all", help="soft-stop every job")
    stop_all.add_argument("--reason", required=True)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    action = "stop_job" if args.command == "stop" else "stop_all"
    path = write_control_request(
        args.run_dir,
        action=action,
        job_id=getattr(args, "job_id", None),
        reason=args.reason,
    )
    print(path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
