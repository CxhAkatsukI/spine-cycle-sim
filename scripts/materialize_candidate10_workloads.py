#!/usr/bin/env python3
"""Materialize source-bound candidate-10 hardware calibration workloads."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from spine_cycle_sim.experiments.candidate10_workloads import (  # noqa: E402
    materialize_candidate10_workloads,
)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out-dir", type=Path, required=True)
    parser.add_argument(
        "--roles",
        default="calibration,holdout",
        help="comma-separated calibration, holdout, and/or stress roles",
    )
    args = parser.parse_args()
    roles = tuple(role for role in args.roles.split(",") if role)
    result = materialize_candidate10_workloads(args.out_dir, roles=roles)
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
