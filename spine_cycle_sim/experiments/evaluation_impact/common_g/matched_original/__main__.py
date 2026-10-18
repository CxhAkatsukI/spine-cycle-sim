"""No-device same-input G host prerequisite."""

import argparse
from pathlib import Path

from .preflight import run
from spine_cycle_sim.experiments.upstream_controls.grasu.hardware.board.execution import PREFLIGHT_SHA256


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("root", "integration", "original-preflight", "xrt", "output"):
        parser.add_argument("--" + name, required=True, type=Path)
    parser.add_argument("--original-preflight-sha256", default=PREFLIGHT_SHA256)
    args = parser.parse_args()
    run(args.root.resolve(), args.integration.resolve(), args.original_preflight.resolve(),
        args.xrt.resolve(), args.output.resolve(), original_preflight_sha256=args.original_preflight_sha256)


if __name__ == "__main__":
    main()
