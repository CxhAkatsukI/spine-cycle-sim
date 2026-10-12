"""Package the cross-row resident matrix using the shared portable evidence gates."""

import argparse
import json
from pathlib import Path

from ..model_delivery import deliver_resident, verify
from .model_study import CROSS_ROW


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run", type=Path)
    parser.add_argument("--plugin", type=Path)
    parser.add_argument("--destination", type=Path, required=True)
    parser.add_argument("--verify-only", action="store_true")
    args = parser.parse_args()
    destination = args.destination.resolve()
    if args.verify_only:
        result = verify(destination, model=CROSS_ROW)
    else:
        if not args.run or not args.plugin:
            parser.error("--run and --plugin are required for delivery")
        deliver_resident(args.run.resolve(), args.plugin.resolve(), destination, model=CROSS_ROW)
        result = verify(destination, model=CROSS_ROW)
    print(json.dumps({"status": result["status"], "portable_recheck": "PASS"}))


if __name__ == "__main__":
    main()
