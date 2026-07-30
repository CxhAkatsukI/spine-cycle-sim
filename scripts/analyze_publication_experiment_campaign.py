#!/usr/bin/env python3
"""Analyze correctness-gated formal campaign case results."""

from __future__ import annotations

import argparse
from pathlib import Path
import sys


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from spine_cycle_sim.experiments.publication_analysis import (  # noqa: E402
    analyze_publication_case_results,
    capacity_exclusion_metadata,
    expected_execution_ids,
    expected_execution_metadata,
    load_case_results,
    write_publication_analysis,
)
from spine_cycle_sim.experiments.large_graph_campaign import (  # noqa: E402
    load_large_graph_campaign_contract,
)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--result-root", type=Path, action="append", required=True)
    parser.add_argument("--manifest", type=Path, action="append", default=[])
    parser.add_argument("--out-dir", type=Path, required=True)
    parser.add_argument("--result-transition-contract", type=Path)
    parser.add_argument("--require-complete", action="store_true")
    args = parser.parse_args()
    results = load_case_results(args.result_root)
    execution_metadata = expected_execution_metadata(args.manifest)
    transition_policy = None
    if args.result_transition_contract is not None:
        transition_contract = load_large_graph_campaign_contract(
            args.result_transition_contract
        )
        transition_policy = transition_contract["architecture_baselines"][
            "simulator_baseline"
        ].get("result_supersedence")
    analysis = analyze_publication_case_results(
        results,
        expected_execution_ids=expected_execution_ids(args.manifest),
        expected_execution_records=execution_metadata,
        capacity_exclusion_records=capacity_exclusion_metadata(args.manifest),
        result_supersedence_policy=transition_policy,
        require_complete=args.require_complete,
    )
    write_publication_analysis(args.out_dir, analysis)
    print(
        f"{analysis['status']} publication campaign: "
        f"observed={analysis['observed_executions']} "
        f"pairs={len(analysis['pair_rows'])} "
        f"missing={len(analysis['missing_execution_ids'])}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
