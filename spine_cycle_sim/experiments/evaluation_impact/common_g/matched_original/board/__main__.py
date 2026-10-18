"""Run the matched production-G FPGA matrix only after strict artifact admission."""

import argparse
from pathlib import Path

from .execution import run


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("preflight", "original-preflight", "returned", "parent", "original", "output"):
        parser.add_argument("--" + name, type=Path, required=True)
    parser.add_argument("--receipt-sha256", required=True)
    parser.add_argument("--device", type=int, default=0)
    parser.add_argument("--repeats", type=int, default=3)
    parser.add_argument("--execute", action="store_true", required=True)
    args = vars(parser.parse_args())
    args.pop("execute")
    for key, value in args.items():
        if isinstance(value, Path):
            args[key] = value.resolve()
    print(run(**args)["status"], flush=True)


if __name__ == "__main__":
    main()
