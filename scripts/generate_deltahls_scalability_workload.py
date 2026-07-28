#!/usr/bin/env python3
"""Generate the balanced four-partition Delta.hls scalability fixture."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from spine_cycle_sim.experiments.deltahls_workloads import (  # noqa: E402
    balanced_partition_scalability_fixture,
)
from spine_cycle_sim.experiments.shared_workloads import (  # noqa: E402
    sha256_file,
    write_slice,
)


DEFAULT_OUT_DIR = ROOT / "tests/data/deltahls_scalability"
DEFAULT_MANIFEST = (
    ROOT / "configs/experiments/deltahls_sinkfree_scalability_p4_v1.json"
)


def _relative(path: Path) -> str:
    return str(path.resolve().relative_to(ROOT))


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out-dir", type=Path, default=DEFAULT_OUT_DIR)
    parser.add_argument("--manifest", type=Path, default=DEFAULT_MANIFEST)
    parser.add_argument("--partition-vertices", type=int, default=65_536)
    parser.add_argument("--partitions", type=int, default=4)
    args = parser.parse_args()

    fixture = balanced_partition_scalability_fixture(
        partition_vertices=args.partition_vertices, partitions=args.partitions
    )
    args.out_dir.mkdir(parents=True, exist_ok=True)
    graph_path = args.out_dir / f"{fixture.graph.case_id}.slice"
    update_path = args.out_dir / f"{fixture.update.case_id}.slice"
    write_slice(graph_path, fixture.graph)
    write_slice(update_path, fixture.update)
    run = {
        "run_id": "deltahls_balanced_matching_p4_insert_u4",
        "dataset_id": "balanced_matching_p4_sinkfree",
        "dataset_kind": "synthetic_balanced_four_partition_sinkfree",
        "role": "scalability",
        "scenario": "insert",
        "user_mutations": fixture.partitions,
        "physical_records": len(fixture.update.records),
        "final_edges": len(fixture.graph.records) + len(fixture.update.records),
        "graph": {
            "case_id": fixture.graph.case_id,
            "path": _relative(graph_path),
            "vertices": fixture.graph.vertices,
            "records": len(fixture.graph.records),
            "sha256": sha256_file(graph_path),
        },
        "update": {
            "case_id": fixture.update.case_id,
            "path": _relative(update_path),
            "vertices": fixture.update.vertices,
            "records": len(fixture.update.records),
            "sha256": sha256_file(update_path),
        },
    }
    manifest = {
        "schema_version": 1,
        "matrix_id": "deltahls_sinkfree_scalability_p4_v1",
        "claim_class": "synthetic_balanced_partition_scalability_contract",
        "partition_vertices": fixture.partition_vertices,
        "partitions": fixture.partitions,
        "invariants": {
            "old_snapshot_sinks": 0,
            "new_snapshot_sinks": 0,
            "weighted_reciprocal_edges": True,
            "one_sided_updates_rejected": True,
            "balanced_partition_records": True,
            "all_partitions_touched": True,
        },
        "runs": [run],
        "limitations": [
            "This is a synthetic balanced matching graph for K scaling, not a real topology.",
            "One reciprocal insertion is applied independently in each partition.",
        ],
    }
    args.manifest.parent.mkdir(parents=True, exist_ok=True)
    args.manifest.write_text(
        json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="ascii"
    )
    print(
        f"PASS Delta.hls scalability workload: vertices={fixture.graph.vertices} "
        f"edges={len(fixture.graph.records)} partitions={fixture.partitions}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
