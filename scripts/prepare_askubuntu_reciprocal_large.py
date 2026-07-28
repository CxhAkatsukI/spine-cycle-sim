#!/usr/bin/env python3
"""Prepare the >=540k-record derived-real CC/Delta.hls workload matrix."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import sys


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from spine_cycle_sim.experiments.connected_components_workloads import (  # noqa: E402
    analyze_reciprocal_update,
    connected_components_labels,
    materialize_reciprocal_update,
)
from spine_cycle_sim.experiments.large_reciprocal_workloads import (  # noqa: E402
    build_large_reciprocal_fixture,
)
from spine_cycle_sim.experiments.shared_workloads import (  # noqa: E402
    load_slice,
    sha256_file,
    write_slice,
)


DEFAULT_SOURCE = (
    ROOT
    / "tests/data/candidate10_askubuntu_paper_scale/sx_askubuntu_base_e540000.slice"
)
DEFAULT_OUT_DIR = ROOT / "tests/data/askubuntu_reciprocal_large"
DEFAULT_MANIFEST = (
    ROOT / "configs/experiments/askubuntu_reciprocal_large_v1.json"
)


def _relative(path: Path) -> str:
    return str(path.resolve().relative_to(ROOT))


def _labels_sha256(labels: tuple[int, ...]) -> str:
    encoded = ",".join(str(label) for label in labels).encode("ascii")
    return hashlib.sha256(encoded).hexdigest()


def build_outputs(
    source_path: Path,
    out_dir: Path,
    manifest_path: Path,
    *,
    target_records: int,
) -> dict[str, object]:
    source = load_slice(source_path)
    fixture = build_large_reciprocal_fixture(
        source,
        target_records=target_records,
    )
    out_dir.mkdir(parents=True, exist_ok=True)
    graph_path = out_dir / f"{fixture.graph.case_id}.slice"
    write_slice(graph_path, fixture.graph)
    initial_labels = connected_components_labels(fixture.graph)
    runs: list[dict[str, object]] = []
    for size, update in sorted(fixture.updates.items()):
        update_path = out_dir / f"{update.case_id}.slice"
        write_slice(update_path, update)
        analysis = analyze_reciprocal_update(fixture.graph, update)
        final = materialize_reciprocal_update(fixture.graph, update)
        final_labels = connected_components_labels(final)
        runs.append(
            {
                "run_id": f"askubuntu_reciprocal_large_bridge_u{size}",
                "dataset_id": "sx_askubuntu_reciprocal_gate",
                "dataset_kind": "derived_real_ordered_undirected_projection",
                "workload_class": "large_real_component_bridge",
                "role": "large_real_pilot" if size in {1, 8, 64} else "large_real_dense",
                "scenario": "insert",
                "algorithm_contract": "weakly_connected_min_vertex_reciprocal_v1",
                "update_mode": "insertion_incremental_repair",
                "user_mutations": size,
                "logical_user_mutations": analysis.logical_user_mutations,
                "effective_mutations": analysis.effective_mutations,
                "physical_records": analysis.physical_records,
                "touched_vertices": len(analysis.touched_vertices),
                "initial_components": len(set(initial_labels)),
                "final_components": len(set(final_labels)),
                "final_edges": len(final.records),
                "final_labels_sha256": _labels_sha256(final_labels),
                "graph": {
                    "case_id": fixture.graph.case_id,
                    "path": _relative(graph_path),
                    "vertices": fixture.graph.vertices,
                    "records": len(fixture.graph.records),
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
    manifest: dict[str, object] = {
        "schema_version": 1,
        "matrix_id": "askubuntu_reciprocal_large_v1",
        "claim_class": "derived_real_topology_large_reciprocal_gate",
        "source": {
            "case_id": source.case_id,
            "path": _relative(source_path),
            "vertices": source.vertices,
            "records": len(source.records),
            "sha256": sha256_file(source_path),
        },
        "transformation": {
            "id": "ordered_unique_undirected_prefix_compact_reciprocal_v1",
            "source_records_scanned": fixture.source_pairs_scanned,
            "selected_undirected_pairs": fixture.selected_pairs,
            "output_reciprocal_records": len(fixture.graph.records),
            "nested_component_bridge_updates": True,
        },
        "invariants": {
            "old_snapshot_sinks": 0,
            "new_snapshot_sinks": 0,
            "weighted_reciprocal_edges": True,
            "one_sided_updates_rejected": True,
            "minimum_external_vertex_label": True,
            "dual_oracle_required": True,
        },
        "runs": runs,
        "limitations": [
            "The graph is a deterministic reciprocal projection of real AskUbuntu topology, not the original directed graph.",
            "The 540000 reciprocal records represent 270000 unique undirected pairs.",
            "Component-bridge insertions are deterministic derived updates, not original temporal events.",
            "Compact remapping changes original destination-partition occupancy.",
        ],
    }
    manifest_path.parent.mkdir(parents=True, exist_ok=True)
    manifest_path.write_text(
        json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="ascii"
    )
    return manifest


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, default=DEFAULT_SOURCE)
    parser.add_argument("--out-dir", type=Path, default=DEFAULT_OUT_DIR)
    parser.add_argument("--manifest", type=Path, default=DEFAULT_MANIFEST)
    parser.add_argument("--target-records", type=int, default=540_000)
    args = parser.parse_args()
    manifest = build_outputs(
        args.source.resolve(),
        args.out_dir.resolve(),
        args.manifest.resolve(),
        target_records=args.target_records,
    )
    graph = manifest["runs"][0]["graph"]
    print(
        "PASS AskUbuntu reciprocal large workload: "
        f"vertices={graph['vertices']} records={graph['records']} "
        f"runs={len(manifest['runs'])}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
