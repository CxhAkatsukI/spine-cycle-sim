#!/usr/bin/env python3
"""Inspect complete fetched upstream history without changing accepted sources."""

import argparse
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from spine_cycle_sim.experiments.publication_admission.history.study import collect, run


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--worker", action="store_true", help=argparse.SUPPRESS)
    args = parser.parse_args()
    report = (collect if args.worker else run)(ROOT, args.out.resolve())
    print(report["status"], flush=True)


if __name__ == "__main__":
    main()
