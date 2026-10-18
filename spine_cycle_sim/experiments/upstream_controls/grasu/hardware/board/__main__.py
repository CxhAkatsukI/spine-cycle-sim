"""No-device original G host preflight command."""

import argparse
from pathlib import Path

from .preflight import run


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("root", "baseline", "xrt", "output"):
        parser.add_argument("--" + name, type=Path, required=True)
    args = parser.parse_args()
    result = run(*(getattr(args, name).resolve() for name in ("root", "baseline", "xrt", "output")))
    print(result["status"])


if __name__ == "__main__":
    main()
