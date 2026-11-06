"""Freeze CPU-labelled workloads before measuring either architecture."""

import argparse
from pathlib import Path

from ...original_regraph_execution.hardware.source_retention.runtime import identity, save
from . import cc, sssp


def prepare(graph_path, output, dataset, source, *, max_updates=131072, algorithm="weighted_sssp",
            targets=sssp.TARGETS, include_ordinary=True):
    output.mkdir(parents=True, exist_ok=False)
    graph = sssp.Graph.load(graph_path)
    if algorithm == "weighted_sssp":
        rows, context = sssp.construct(graph, source, max_updates=max_updates,
                                      targets=targets, include_ordinary=include_ordinary)
        reference = "full_positive_integer_dijkstra_old_and_new"
    else:
        rows, context = cc.construct(graph, max_updates=max_updates)
        reference = "canonical_minimum_union_find_old_and_new"
    manifest = dict(algorithm=algorithm, dataset=dataset, source=source,
                    vertices=graph.vertices, edges=len(graph.edges), original=identity(graph_path),
                    preparation=[identity(__file__), identity(sssp.__file__), identity(cc.__file__)],
                    context=context, points=[])
    for row in rows:
        batch = row.pop("batch")
        path = output / (row["name"] + ".graph")
        graph.write(path, batch)
        manifest["points"].append(dict(row, graph=identity(path), updates=len(batch),
                                       changed_fraction=row["changed_vertices"] / graph.vertices,
                                       cpu_reference=reference))
    save(output / "workloads.json", manifest)
    return manifest


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--graph", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--dataset", required=True)
    parser.add_argument("--source", type=int, required=True)
    parser.add_argument("--algorithm", choices=("weighted_sssp", "connected_components"), default="weighted_sssp")
    parser.add_argument("--max-updates", type=int, default=131072)
    parser.add_argument("--target-fraction", type=float, action="append")
    parser.add_argument("--no-ordinary", action="store_true")
    args = parser.parse_args()
    if args.algorithm != "weighted_sssp" and (args.target_fraction or args.no_ordinary):
        parser.error("custom target/ordinary selection currently applies to SSSP only")
    result = prepare(args.graph, args.output, args.dataset, args.source, max_updates=args.max_updates,
                     algorithm=args.algorithm, targets=args.target_fraction or sssp.TARGETS,
                     include_ordinary=not args.no_ordinary)
    for point in result["points"]:
        print(point["name"], point["updates"], point["changed_vertices"], point["changed_fraction"], flush=True)


if __name__ == "__main__":
    main()
