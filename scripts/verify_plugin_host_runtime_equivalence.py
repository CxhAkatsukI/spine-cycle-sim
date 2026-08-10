#!/usr/bin/env python3
"""Compare two SST summaries after removing host-runtime provenance only."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from spine_cycle_sim.experiments.plugin_equivalence import (  # noqa: E402
    compare_host_runtime_summaries,
)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--baseline-summary", type=Path, required=True)
    parser.add_argument("--candidate-summary", type=Path, required=True)
    parser.add_argument("--label", required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    report = compare_host_runtime_summaries(
        args.baseline_summary, args.candidate_summary, label=args.label
    )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="ascii"
    )
    print(
        f"PASS {args.label}: cycles={report['simulated_metrics']['cycles']} "
        f"requests={report['simulated_metrics']['backend_requests']}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
