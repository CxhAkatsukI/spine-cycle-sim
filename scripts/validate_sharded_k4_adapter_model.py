#!/usr/bin/env python3
"""Compare production HLS and the finite adapter model on shared packet fixtures."""

import argparse
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from spine_cycle_sim.experiments.sharded_k4_stages.model_adapter import validate_adapter


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--integration", required=True, type=Path)
    parser.add_argument("--vitis-include", required=True, type=Path)
    parser.add_argument("--core-build", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    validate_adapter(root=ROOT, integration=args.integration.resolve(),
                     vitis=args.vitis_include.resolve(), core_build=args.core_build.resolve(),
                     output=args.output.resolve())


if __name__ == "__main__":
    main()
