#!/usr/bin/env python3
"""Compare admitted original/candidate K4 hardware using one unchanged host."""

import argparse
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from spine_cycle_sim.experiments.sharded_k4_stages.comparison import compare_bitstreams

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("integration", "matrix", "host", "admission", "output"):
        parser.add_argument("--" + name, type=Path, required=True)
    parser.add_argument("--case", required=True)
    parser.add_argument("--repeats", type=int, default=3)
    parser.add_argument("--device", type=int, default=0)
    print(compare_bitstreams(**vars(parser.parse_args()))["status"])
