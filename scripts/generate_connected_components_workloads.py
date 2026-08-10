#!/usr/bin/env python3
"""Generate the frozen connected-components workload and oracle manifest."""

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
    ConnectedComponentsFixture,
    analyze_reciprocal_update,
    connected_components_labels,
    formal_connected_components_fixtures,
    materialize_reciprocal_update,
)
from spine_cycle_sim.experiments.shared_workloads import (  # noqa: E402
    SliceGraph,
    SliceRecord,
    load_slice,
    sha256_file,
    write_slice,
)


DEFAULT_OUT_DIR = ROOT / "tests/data/connected_components_formal"
DEFAULT_MANIFEST = ROOT / "configs/experiments/connected_components_formal_v1.json"
REAL_BASE = ROOT / "tests/data/deltahls_real/real_soc_flickr_und_reciprocal_sinkfree.slice"
REAL_UPDATES = tuple(
    ROOT / f"tests/data/deltahls_real/real_soc_flickr_und_insert_u{size}.slice"
    for size in (1, 8, 64, 4096)
)


def _relative(path: Path) -> str:
    return str(path.resolve().relative_to(ROOT))


def _labels_sha256(labels: tuple[int, ...]) -> str:
    payload = ",".join(str(label) for label in labels).encode("ascii")
    return hashlib.sha256(payload).hexdigest()


def _real_fixtures() -> tuple[ConnectedComponentsFixture, ...]:
    if not REAL_BASE.is_file() or any(not path.is_file() for path in REAL_UPDATES):
        return ()
    graph = load_slice(REAL_BASE)
    fixtures = tuple(
        ConnectedComponentsFixture(
            fixture_id=f"cc_real_soc_flickr_insert_u{len(update.records) // 2}",
            workload_class="real_topology_component_merge",
            role="real_screening" if len(update.records) < 8192 else "real_dense",
            graph=graph,
            update=update,
        )
        for update in (load_slice(path) for path in REAL_UPDATES)
    )
    unit_update = load_slice(REAL_UPDATES[0])
    partition_span = 65_536
    replicas = 4
    records_per_replica = 2_048
    multipliers = (1, 3, 5, 7)
    shifts = (0, 8192, 16_384, 24_576)

    by_endpoints = {(edge.src, edge.dst): edge for edge in graph.records}
    canonical = [edge for edge in graph.records if edge.src < edge.dst]
    if len(canonical) * 2 != len(graph.records):
        raise ValueError("Flickr CC scalability base must be exactly reciprocal")
    selected_pairs = [
        canonical[(index * len(canonical)) // (records_per_replica // 2)]
        for index in range(records_per_replica // 2)
    ]
    scalability_records = tuple(
        sorted(
            edge
            for forward in selected_pairs
            for edge in (
                forward,
                by_endpoints[(forward.dst, forward.src)],
            )
        )
    )

    def replicated_vertex(vertex: int, replica: int) -> int:
        local = (vertex * multipliers[replica] + shifts[replica]) % partition_span
        return replica * partition_span + local

    replicated_graph = SliceGraph(
        "cc_real_soc_flickr_replicated_p4_base",
        partition_span * replicas,
        tuple(sorted(
            SliceRecord(
                replicated_vertex(edge.src, replica),
                replicated_vertex(edge.dst, replica),
                edge.weight,
                edge.diff,
            )
            for replica in range(replicas)
            for edge in scalability_records
        )),
    )
    replicated_update = SliceGraph(
        "cc_real_soc_flickr_replicated_p4_insert_u4",
        partition_span * replicas,
        tuple(sorted(
            SliceRecord(
                replicated_vertex(edge.src, replica),
                replicated_vertex(edge.dst, replica),
                edge.weight,
                edge.diff,
            )
            for replica in range(replicas)
            for edge in unit_update.records
        )),
    )
    return fixtures + (
        ConnectedComponentsFixture(
            fixture_id="cc_real_soc_flickr_replicated_p4_insert_u4",
            workload_class="replicated_real_topology_four_partition",
            role="scalability",
            graph=replicated_graph,
            update=replicated_update,
        ),
    )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out-dir", type=Path, default=DEFAULT_OUT_DIR)
    parser.add_argument("--manifest", type=Path, default=DEFAULT_MANIFEST)
    args = parser.parse_args()

    fixtures = formal_connected_components_fixtures() + _real_fixtures()
    args.out_dir.mkdir(parents=True, exist_ok=True)
    written: dict[str, Path] = {}
    runs: list[dict[str, object]] = []
    for fixture in fixtures:
        graph_path = written.get(fixture.graph.case_id)
        if graph_path is None:
            graph_path = args.out_dir / f"{fixture.graph.case_id}.slice"
            write_slice(graph_path, fixture.graph)
            written[fixture.graph.case_id] = graph_path
        update_path = args.out_dir / f"{fixture.update.case_id}.slice"
        write_slice(update_path, fixture.update)

        analysis = analyze_reciprocal_update(fixture.graph, fixture.update)
        final = materialize_reciprocal_update(fixture.graph, fixture.update)
        initial_labels = connected_components_labels(fixture.graph)
        final_labels = connected_components_labels(final)
        runs.append(
            {
                "run_id": fixture.fixture_id,
                "workload_class": fixture.workload_class,
                "role": fixture.role,
                "algorithm_contract": "weakly_connected_min_vertex_reciprocal_v1",
                "update_mode": (
                    "zero_net_no_repair"
                    if analysis.zero_net
                    else "deletion_full_recompute"
                    if analysis.deletions
                    else "insertion_incremental_repair"
                ),
                "logical_user_mutations": analysis.logical_user_mutations,
                "effective_mutations": analysis.effective_mutations,
                "physical_records": analysis.physical_records,
                "touched_vertices": len(analysis.touched_vertices),
                "initial_components": len(set(initial_labels)),
                "final_components": len(set(final_labels)),
                "final_edges": len(final.records),
                "final_labels_sha256": _labels_sha256(final_labels),
                "graph": {
                    "path": _relative(graph_path),
                    "case_id": fixture.graph.case_id,
                    "vertices": fixture.graph.vertices,
                    "records": len(fixture.graph.records),
                    "sha256": sha256_file(graph_path),
                },
                "update": {
                    "path": _relative(update_path),
                    "case_id": fixture.update.case_id,
                    "vertices": fixture.update.vertices,
                    "records": len(fixture.update.records),
                    "sha256": sha256_file(update_path),
                },
            }
        )

    manifest = {
        "schema_version": 1,
        "matrix_id": "connected_components_formal_v1",
        "algorithm_contract": "weakly_connected_min_vertex_reciprocal_v1",
        "invariants": {
            "atomic_reciprocal_updates": True,
            "one_sided_updates_rejected": True,
            "minimum_external_vertex_label": True,
            "insertion_warm_start": True,
            "deletion_full_recompute": True,
            "dual_oracle_required": True,
        },
        "runs": runs,
        "limitations": [
            "Controlled semantic and dense fixtures are synthetic reciprocal graphs.",
            "The Flickr rows use a compact real-edge slice with deterministic reciprocal closure.",
            "The frozen Flickr slice begins with 24 components; the manifest records how each batch merges them.",
        ],
    }
    args.manifest.parent.mkdir(parents=True, exist_ok=True)
    args.manifest.write_text(
        json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="ascii"
    )
    print(
        f"PASS CC workloads: runs={len(runs)} files={len(written) + len(fixtures)} "
        f"manifest={args.manifest}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
