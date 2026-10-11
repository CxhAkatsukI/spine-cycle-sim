#!/usr/bin/env python3
"""Run the controlled FPGA/model empty-row sweep without timing fitting."""

import argparse
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from spine_cycle_sim.experiments.sharded_k4_stages.row_sweep import run_sweep

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("integration", "host", "admission", "exporter", "plugin-dir", "channel-evidence", "output"):
        parser.add_argument("--" + name, type=Path, required=True)
    parser.add_argument("--contract-path", type=Path, default=Path("configs/experiments/sharded_k4_empty_rows_v1.json"))
    parser.add_argument("--device", type=int, default=0)
    print(run_sweep(root=Path(__file__).resolve().parents[1], **vars(parser.parse_args()))["status"])
