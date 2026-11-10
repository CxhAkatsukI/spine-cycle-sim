"""Prepare the single-batch Fig. 7 roadNet-CA extension without running hardware."""

import argparse
import filecmp
from pathlib import Path
import tempfile

from spine_cycle_sim.experiments import publication_workloads as workload
from spine_cycle_sim.experiments.original_regraph_execution.hardware.source_retention.runtime import (
    identity, save,
)


VERTICES = 1_965_206
ID_SPACE = 1_971_281
ARCS = 5_533_214
SNAP_SHA256 = "383f7b14424530a9e25c392969a9c19dace32ebcfd141f0967a1433498c2acdd"
ALGORITHMS = {
    "weighted_sssp": "directed",
    "connected_components": "reciprocal",
    "residual_pagerank": "residual_sink_free",
}


def prepare(source, output):
    pin = identity(source)
    if pin["sha256"] != SNAP_SHA256:
        raise ValueError("unexpected SNAP roadNet-CA archive")
    output.mkdir(parents=True, exist_ok=False)
    spec = workload.PublicationSourceSpec(
        "roadNet-CA", source, "gzip_temporal_src_dst_timestamp",
        declared_vertices=ID_SPACE, expected_unique_edges=ARCS,
    )
    seed = workload.WEIGHT_SEED
    summary = dict(dataset="RN", snap=pin, vertices=VERTICES, id_space=ID_SPACE, directed_arcs=ARCS,
                   undirected_roads=ARCS // 2, seed=seed, algorithms={})
    with tempfile.TemporaryDirectory(dir=output) as temporary:
        work = Path(temporary)
        raw, keys = work / "base.raw", work / "base.keys"
        normalized = workload._normalize_source(
            spec, base_raw=raw, post_base_raw=work / "post.raw", progress_path=None,
        )
        options = dict(temp_dir=work, parallel=1, memory="128M",
                       spec=spec, progress_path=None)
        workload._sort_unique(raw, keys, phase="sort_base", **options)
        if (normalized["raw_records"] != ARCS or workload._line_count(keys) != ARCS
                or normalized["max_normalized_vertex_id"] != ID_SPACE - 1
                or workload._unique_source_count(keys) != VERTICES):
            raise ValueError("expected unique arcs with every original vertex represented")
        workload._make_reciprocal_raw(keys, raw)
        reciprocal = work / "reciprocal.keys"
        workload._sort_unique(raw, reciprocal, phase="verify_reciprocal", **options)
        if not filecmp.cmp(keys, reciprocal, shallow=False):
            raise ValueError("roadNet-CA arcs are not reciprocal")
        source_id = workload._source_cohorts(keys, seed=seed + 503)["median_degree"]
        residual = work / "residual.keys"
        workload._make_sink_free_keys(keys, residual, ID_SPACE)
        added_loops = ID_SPACE - VERTICES
        if workload._line_count(residual) != ARCS + added_loops:
            raise ValueError("unexpected residual sink completion")
        summary.update(normalization=normalized, median_degree_source=source_id,
                       reciprocal=True, residual_sink_loops_added=added_loops)

        for algorithm, projection in ALGORITHMS.items():
            # The SNAP IDs are sparse; only the PR projection fills missing
            # IDs with self-loops for the existing sink-free host contract.
            initial_keys = residual if projection == "residual_sink_free" else keys
            initial_edges = ARCS + (added_loops if initial_keys == residual else 0)
            case = output / algorithm
            case.mkdir()
            (case / ".work").mkdir()
            updates = workload._derive_projection_updates(
                output_dir=case, vertices=ID_SPACE, projection=projection,
                graph_keys=initial_keys, delete_keys=keys, post_base_keys=None,
                batch_sizes=(8,), seed=seed, reciprocal=projection == "reciprocal",
            )
            insert = next(item for item in updates if item["scenario"] == "insert")
            with Path(insert["path"]).open() as stream:
                batch = [line.strip() for line in stream if not line.startswith("#")]
            graph = case / "insert-u8.graph"
            records = [list(map(int, line.split())) for line in batch]
            unseen = {vertex for src, dst, _, _ in records for vertex in (src, dst)}
            with graph.open("x") as stream, initial_keys.open() as initial:
                stream.write(f"{ID_SPACE} {initial_edges} {len(batch)}\n")
                for line in initial:
                    src, dst = map(int, line.split())
                    if src != dst:
                        unseen.discard(src)
                    stream.write(f"{src} {dst} {workload.canonical_edge_weight(src, dst)}\n")
                stream.write("\n".join(batch) + "\n")
            if unseen or len(batch) != (16 if projection == "reciprocal" else 8):
                raise ValueError("batch must contain eight real-vertex insertions")
            point = dict(name="insert-u8", graph=identity(graph), updates=len(batch),
                         logical_insertions=8, batch=records,
                         changed_fraction=None)
            manifest = dict(dataset="RN", algorithm=algorithm, vertices=ID_SPACE, edges=initial_edges,
                            source=0 if algorithm == "residual_pagerank" else source_id,
                            projection=projection, points=[point])
            if algorithm == "residual_pagerank":
                manifest["epsilon"] = 1e-6
            else:
                # The road graph exceeds the earlier workloads' 256-round cap.
                manifest["gr_max_supersteps"] = 1024
            save(case / "workloads.json", manifest)
            summary["algorithms"][algorithm] = manifest
            print(algorithm, point["graph"]["sha256"], flush=True)
    save(output / "input_manifest.json", summary)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("source", type=Path)
    parser.add_argument("output", type=Path)
    args = parser.parse_args()
    prepare(args.source.resolve(), args.output.resolve())
