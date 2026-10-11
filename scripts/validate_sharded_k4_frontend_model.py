#!/usr/bin/env python3
"""Run the independently bounded routed Scatter/source component gates."""

import argparse
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from spine_cycle_sim.experiments.sharded_k4_stages.model_frontend import validate_frontend


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--integration", type=Path, required=True)
    parser.add_argument("--regraph", type=Path, required=True)
    parser.add_argument("--vitis", type=Path, required=True)
    parser.add_argument("--core-build", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--routed-hbm-xo", type=Path, required=True)
    parser.add_argument("--route-manifest", type=Path, required=True)
    parser.add_argument("--compile-inputs", type=Path, required=True)
    args = parser.parse_args()
    result = validate_frontend(root=ROOT, integration=args.integration.resolve(), regraph=args.regraph.resolve(),
                               vitis=args.vitis.resolve(), core_build=args.core_build.resolve(), output=args.output.resolve(),
                               routed_hbm_xo=args.routed_hbm_xo.resolve(), route_manifest=args.route_manifest.resolve(),
                               compile_inputs=args.compile_inputs.resolve())
    print(result["status"] + ": routed frontend component gates; not hardware timing")


if __name__ == "__main__":
    main()
