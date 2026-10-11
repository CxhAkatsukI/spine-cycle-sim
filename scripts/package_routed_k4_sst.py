#!/usr/bin/env python3
"""Freeze validated routed SSSP SST diagnostics without changing existing evidence."""

import argparse
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from spine_cycle_sim.experiments.sharded_k4_stages.sst_delivery import package_sst_checkpoint


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("integration", "data", "output"):
        parser.add_argument(f"--{name}", required=True, type=Path)
    args = parser.parse_args()
    result = package_sst_checkpoint(ROOT, args.integration.resolve(), args.data.resolve(), args.output.resolve())
    print(result["status"], flush=True)


if __name__ == "__main__":
    main()
