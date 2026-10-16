"""Prepare all frozen full-graph inputs without invoking FPGA APIs."""

import argparse
from pathlib import Path

from .analysis import PASS
from .study import run

parser = argparse.ArgumentParser(description=__doc__)
for name in ("integration", "manifest", "output", "xrt", "hls"):
    parser.add_argument("--" + name, type=Path, required=True)
parser.add_argument("--wait-seconds", type=int, default=64800)
args = parser.parse_args()
result = run(*(getattr(args, name).resolve() for name in ("integration", "manifest", "output", "xrt", "hls")),
             wait_seconds=args.wait_seconds)
print(result["status"], flush=True)
raise SystemExit(0 if result["status"] == PASS else 1)
