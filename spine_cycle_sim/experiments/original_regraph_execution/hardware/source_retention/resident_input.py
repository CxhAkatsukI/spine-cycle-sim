"""Prepare a common, sink-free ResPR input for both resident FPGA hosts."""

import argparse
from pathlib import Path

from spine_cycle_sim.experiments.shared_workloads import SliceGraph, load_slice


def _reciprocal_insertions(graph: SliceGraph) -> dict[tuple[int, int], int]:
    edges: dict[tuple[int, int], int] = {}
    for edge in graph.records:
        key = (edge.src, edge.dst)
        if (not 0 <= edge.src < graph.vertices
                or not 0 <= edge.dst < graph.vertices
                or edge.src == edge.dst
                or not 1 <= edge.weight <= 0xFFF
                or edge.diff != 1 or key in edges):
            raise ValueError(f"{graph.case_id}: invalid or duplicate edge {edge}")
        edges[key] = edge.weight
    if any(edges.get((dst, src)) != weight for (src, dst), weight in edges.items()):
        raise ValueError(f"{graph.case_id}: edges are not weight-matched reciprocal pairs")
    return edges


def prepare(graph_path: Path, update_path: Path, output: Path) -> None:
    graph, update = load_slice(graph_path), load_slice(update_path)
    if graph.vertices <= 0 or graph.vertices != update.vertices:
        raise ValueError("old graph and batch must have the same positive vertex extent")
    initial = _reciprocal_insertions(graph)
    inserts = _reciprocal_insertions(update)
    if not inserts or initial.keys() & inserts.keys():
        raise ValueError("batch must contain only new edges")
    if len({src for src, _ in initial}) != graph.vertices:
        raise ValueError("old graph must be sink-free")

    with output.open("x", encoding="ascii", newline="\n") as stream:
        stream.write(f"{graph.vertices} {len(initial)} {len(inserts)}\n")
        for (src, dst), weight in initial.items():
            stream.write(f"{src} {dst} {weight}\n")
        for (src, dst), weight in inserts.items():
            stream.write(f"{src} {dst} {weight} 1\n")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("graph", type=Path)
    parser.add_argument("updates", type=Path)
    parser.add_argument("output", type=Path)
    args = parser.parse_args()
    prepare(args.graph, args.updates, args.output)


if __name__ == "__main__":
    main()
