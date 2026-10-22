"""Run the finite experimental PMA reader/compactor without promoting a profile."""

import argparse
import json
from pathlib import Path
from .adapter_floor import run


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--reference", type=Path, required=True)
    parser.add_argument("--core-gates", type=Path, required=True)
    parser.add_argument("--cpu", type=int, required=True)
    parser.add_argument("--admission-wait-seconds", type=int, default=600)
    args = parser.parse_args()
    result = run(args.output.resolve(), args.reference.resolve(), args.core_gates.resolve(),
                 args.cpu, args.admission_wait_seconds, candidate=True)
    print(json.dumps({"status": result["status"], "analysis": result["analysis"]}))
