"""Replay the six complete board reports; no FPGA is programmed."""

import argparse
from pathlib import Path

from .study import run


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("preflight", "requests", "output"):
        parser.add_argument("--" + name, required=True, type=Path)
    args = parser.parse_args(argv)
    report = run(args.preflight.resolve(), args.requests.resolve(), args.output.resolve())
    print(report["status"], flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
