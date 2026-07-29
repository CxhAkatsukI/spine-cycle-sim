#!/usr/bin/env python3
"""Generate the de-duplicated formal publication experiment campaign."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from spine_cycle_sim.experiments.large_graph_campaign import (  # noqa: E402
    build_publication_experiment_campaign_manifest,
    load_large_graph_campaign_contract,
)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--contract",
        type=Path,
        default=ROOT / "configs/contracts/large_graph_publication_campaign_v1.json",
    )
    parser.add_argument("--materialization-root", type=Path, required=True)
    parser.add_argument("--output-root", type=Path, required=True)
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--python", default=sys.executable)
    parser.add_argument("--sst", type=Path, default=Path("/data/feiyang/sst/bin/sst"))
    parser.add_argument(
        "--lib-dir",
        type=Path,
        default=Path(
            "/data/tmp/chuxiao/candidate86-cc-unweighted-native-pgo-build-20260729"
        ),
    )
    parser.add_argument(
        "--capability-catalog",
        type=Path,
        default=ROOT
        / "configs/contracts/grasu_regraph_publication_capabilities_v6.json",
    )
    parser.add_argument("--tier", action="append", dest="tiers")
    parser.add_argument("--dataset", action="append", dest="datasets")
    parser.add_argument("--max-cycles", type=int, default=10_000_000_000_000)
    args = parser.parse_args()

    manifest = build_publication_experiment_campaign_manifest(
        load_large_graph_campaign_contract(args.contract),
        materialization_root=args.materialization_root,
        output_root=args.output_root,
        python=args.python,
        sst=args.sst,
        lib_dir=args.lib_dir,
        capability_catalog=args.capability_catalog,
        contract_path=args.contract,
        selected_tiers=set(args.tiers) if args.tiers else None,
        selected_datasets=set(args.datasets) if args.datasets else None,
        max_cycles=args.max_cycles,
    )
    args.manifest.parent.mkdir(parents=True, exist_ok=True)
    args.manifest.write_text(
        json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="ascii"
    )
    print(
        json.dumps(
            {
                "manifest": str(args.manifest.resolve()),
                "logical_views": manifest["logical_view_count"],
                "physical_executions": manifest["physical_execution_count"],
                "jobs": len(manifest["jobs"]),
            },
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
