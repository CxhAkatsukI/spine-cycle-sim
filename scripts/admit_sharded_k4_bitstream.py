#!/usr/bin/env python3
"""Check final routed timing, clock and topology without programming a board."""

import argparse
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from spine_cycle_sim.experiments.sharded_k4_stages.bitstream import admit_bitstream

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("route", "original", "output"):
        parser.add_argument("--" + name, type=Path, required=True)
    print(admit_bitstream(**vars(parser.parse_args()))["status"])
