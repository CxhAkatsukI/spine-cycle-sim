"""Launch a fresh, independently guarded 11-Little/3-Big author-source control."""

import argparse
from pathlib import Path

from .execution import run

parser = argparse.ArgumentParser(description=__doc__)
for name in ("upstream", "audit", "control", "environment", "output"):
    parser.add_argument("--" + name, type=Path, required=True)
args = parser.parse_args()
root = Path(__file__).resolve().parents[5]
print(run(root, *(getattr(args, name).resolve() for name in (
    "upstream", "audit", "control", "environment", "output")))["status"], flush=True)
