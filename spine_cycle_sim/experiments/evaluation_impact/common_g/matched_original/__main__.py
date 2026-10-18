"""No-device same-input G host prerequisite."""

import argparse
from pathlib import Path

from .preflight import run


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("root", "integration", "original-preflight", "xrt", "output"):
        parser.add_argument("--" + name, required=True, type=Path)
    args = parser.parse_args()
    run(args.root.resolve(), args.integration.resolve(), args.original_preflight.resolve(),
        args.xrt.resolve(), args.output.resolve())


if __name__ == "__main__":
    main()
