#!/usr/bin/env python3
"""Render one auditable progress snapshot for a simulator campaign."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from spine_cycle_sim.experiments.campaign_runtime import render_campaign_state


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run-dir", type=Path, required=True)
    parser.add_argument("--max-rows", type=int, default=24)
    parser.add_argument("--json", action="store_true")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    state_path = args.run_dir.resolve() / "campaign_state.json"
    try:
        state = json.loads(state_path.read_text(encoding="ascii"))
    except FileNotFoundError:
        print(f"campaign state does not exist yet: {state_path}", file=sys.stderr)
        return 2
    if args.json:
        print(json.dumps(state, indent=2, sort_keys=True))
    else:
        print(render_campaign_state(state, max_rows=args.max_rows))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
