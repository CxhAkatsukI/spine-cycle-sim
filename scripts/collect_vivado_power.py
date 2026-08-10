#!/usr/bin/env python3
"""Collect a hashed vectorless power report from one routed checkpoint."""

from __future__ import annotations

import argparse
from pathlib import Path
import sys


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from spine_cycle_sim.evidence.vivado_power import collect_vivado_power  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--checkpoint", type=Path, required=True)
    parser.add_argument("--out-dir", type=Path, required=True)
    parser.add_argument("--label", required=True)
    parser.add_argument(
        "--vivado",
        type=Path,
        default=Path("/data/yxx/tools/xilinx/Vivado/2024.1/bin/vivado"),
    )
    args = parser.parse_args()
    report = collect_vivado_power(
        checkpoint=args.checkpoint,
        out_dir=args.out_dir,
        vivado=args.vivado,
        label=args.label,
    )
    print(f"PASS Vivado vectorless power: {report['label']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
