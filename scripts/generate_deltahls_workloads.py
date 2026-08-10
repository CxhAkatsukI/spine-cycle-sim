#!/usr/bin/env python3
"""Generate frozen sink-free Delta.hls/CC workloads and their manifest."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from spine_cycle_sim.experiments.deltahls_workloads import (  # noqa: E402
    DEFAULT_BATCH_SIZES,
    DEFAULT_CANDIDATE_SEED,
    reciprocal_closure,
    reciprocal_insert_batches,
    validate_reciprocal_graph,
    validate_reciprocal_update,
)
from spine_cycle_sim.experiments.shared_workloads import (  # noqa: E402
    load_slice,
    sha256_file,
    write_slice,
)


DEFAULT_SOURCE = ROOT / "tests/data/shared_comparison/real_soc_flickr_und_compact.slice"
DEFAULT_OUT_DIR = ROOT / "tests/data/deltahls_real"
DEFAULT_MANIFEST = ROOT / "configs/experiments/deltahls_sinkfree_real_v1.json"


def _relative(path: Path) -> str:
    return str(path.resolve().relative_to(ROOT))


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, default=DEFAULT_SOURCE)
    parser.add_argument("--out-dir", type=Path, default=DEFAULT_OUT_DIR)
    parser.add_argument("--manifest", type=Path, default=DEFAULT_MANIFEST)
    parser.add_argument(
        "--batch-size", type=int, action="append", dest="batch_sizes"
    )
    parser.add_argument("--seed", type=int, default=DEFAULT_CANDIDATE_SEED)
    args = parser.parse_args()

    source_path = args.source.resolve()
    source = load_slice(source_path)
    closure = reciprocal_closure(
        source, case_id="real_soc_flickr_und_reciprocal_sinkfree"
    )
    validate_reciprocal_graph(closure.graph)
    sizes = tuple(args.batch_sizes or DEFAULT_BATCH_SIZES)
    batches = reciprocal_insert_batches(
        closure.graph,
        sizes,
        case_prefix="real_soc_flickr_und_reciprocal_sinkfree",
        seed=args.seed,
    )

    args.out_dir.mkdir(parents=True, exist_ok=True)
    graph_path = args.out_dir / "real_soc_flickr_und_reciprocal_sinkfree.slice"
    write_slice(graph_path, closure.graph)
    runs = []
    for size, update in sorted(batches.items()):
        validate_reciprocal_update(closure.graph, update)
        update_path = args.out_dir / f"real_soc_flickr_und_insert_u{size}.slice"
        write_slice(update_path, update)
        runs.append(
            {
                "run_id": f"deltahls_soc_flickr_insert_u{size}",
                "dataset_id": "soc_flickr_und_reciprocal_sinkfree",
                "dataset_kind": "real_compact_slice_reciprocal_closure",
                "role": "screening" if size in {1, 8, 64} else "dense",
                "scenario": "insert",
                "user_mutations": size,
                "physical_records": len(update.records),
                "final_edges": len(closure.graph.records) + len(update.records),
                "graph": {
                    "case_id": closure.graph.case_id,
                    "path": _relative(graph_path),
                    "vertices": closure.graph.vertices,
                    "records": len(closure.graph.records),
                    "sha256": sha256_file(graph_path),
                },
                "update": {
                    "case_id": update.case_id,
                    "path": _relative(update_path),
                    "vertices": update.vertices,
                    "records": len(update.records),
                    "sha256": sha256_file(update_path),
                },
            }
        )

    manifest = {
        "schema_version": 1,
        "matrix_id": "deltahls_sinkfree_real_v1",
        "claim_class": "derived_real_topology_reciprocal_sinkfree_input_contract",
        "source": {
            "path": _relative(source_path),
            "sha256": sha256_file(source_path),
            "case_id": source.case_id,
            "vertices": source.vertices,
            "records": len(source.records),
        },
        "transformation": {
            "id": "weighted_reciprocal_closure_v1",
            "preserves_compact_vertex_ids": True,
            "original_records": closure.original_records,
            "reciprocal_records_added": closure.reciprocal_records_added,
            "self_loops": closure.self_loops,
            "candidate_seed": args.seed,
            "nested_insert_batches": True,
            "one_user_mutation_records": 2,
        },
        "invariants": {
            "old_snapshot_sinks": 0,
            "new_snapshot_sinks": 0,
            "weighted_reciprocal_edges": True,
            "one_sided_updates_rejected": True,
        },
        "runs": runs,
        "limitations": [
            "The source is a compact real-edge slice, not the full Flickr graph.",
            "Reciprocal closure is a declared deterministic transformation of the slice.",
            "Insert batches are synthetic but execute on the frozen real topology.",
        ],
    }
    args.manifest.parent.mkdir(parents=True, exist_ok=True)
    args.manifest.write_text(
        json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="ascii"
    )
    print(
        f"PASS Delta.hls workloads: vertices={closure.graph.vertices} "
        f"edges={len(closure.graph.records)} batches={','.join(map(str, sorted(batches)))}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
