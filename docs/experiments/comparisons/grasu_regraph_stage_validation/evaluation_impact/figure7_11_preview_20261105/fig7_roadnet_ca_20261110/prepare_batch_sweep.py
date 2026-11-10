"""Extend the frozen RN insertion batches without changing their initial graphs."""

import argparse
import csv
from contextlib import ExitStack
import json
from pathlib import Path
import random
import subprocess

from spine_cycle_sim.experiments.publication_workloads import canonical_edge_weight
from spine_cycle_sim.experiments.original_regraph_execution.hardware.source_retention.runtime import (
    identity, save,
)


SIZES = (8, 64, 512, 4096)
SEED = 20261110


def extend(graph, vertices, edges, prefix, reciprocal, seed):
    present = bytearray(vertices)
    rng = random.Random(seed)
    key = (lambda u, v: (min(u, v), max(u, v))) if reciprocal else (lambda u, v: (u, v))
    seen = {key(u, v) for u, v, _, _ in prefix}
    candidates = {}
    while len(candidates) < 4 * SIZES[-1]:
        u, v = rng.randrange(vertices), rng.randrange(vertices)
        if u != v and key(u, v) not in seen:
            candidates.setdefault(key(u, v), None)

    with graph.open("rb") as stream:
        next(stream)
        for _ in range(edges):
            src, dst, _ = map(int, next(stream).split())
            if src != dst:
                present[src] = present[dst] = 1
            candidates.pop(key(src, dst), None)

    result = list(prefix)
    for u, v in candidates:
        if present[u] and present[v]:
            weight = canonical_edge_weight(u, v)
            result.append([u, v, weight, 1])
            if reciprocal:
                result.append([v, u, weight, 1])
        if len(result) == SIZES[-1] * (2 if reciprocal else 1):
            return result
    raise ValueError("not enough absent edges with real RN endpoints")


def cpu_result(algorithm, graph, source, oracle, pagerank_oracle, epsilon):
    if algorithm == "residual_pagerank":
        args = [pagerank_oracle, graph, str(epsilon)]
        result = json.loads(subprocess.check_output(args, text=True, timeout=600))
        if not result["converged"]:
            raise ValueError("CPU PR reference did not converge")
        return result
    mode = "cc" if algorithm == "connected_components" else "sssp"
    args = [oracle, mode, graph, str(source)]
    output = subprocess.check_output(args, text=True, timeout=600)
    return {key: int(value) for key, value in (field.split("=") for field in output.split())}


def prepare(base, output, oracle, pagerank_oracle, seed, actual_vertices):
    manifest = json.loads(base.read_text())
    algorithm = manifest["algorithm"]
    original, = manifest["points"]
    graph = Path(original["graph"]["path"])
    if identity(graph) != original["graph"]:
        raise ValueError("the Fig. 7 input changed")
    reciprocal = algorithm == "connected_components"
    vertices, edges = manifest["vertices"], manifest["edges"]
    copies = 2 if reciprocal else 1
    prefix = original["batch"]
    if len(prefix) != SIZES[0] * copies:
        raise ValueError("expected the frozen Fig. 7 eight-insertion batch")
    batch = extend(graph, vertices, edges, prefix, reciprocal, seed)
    paths = {8: graph}
    output.mkdir(parents=True, exist_ok=False)
    with ExitStack() as files:
        source = files.enter_context(graph.open("rb"))
        next(source)
        writers = {}
        for size in SIZES[1:]:
            path = output / f"ordinary-{size}.graph"
            paths[size] = path
            writers[size] = files.enter_context(path.open("xb"))
            writers[size].write(f"{vertices} {edges} {size * copies}\n".encode())
        for _ in range(edges):
            line = next(source)
            for writer in writers.values():
                writer.write(line)
        for size, writer in writers.items():
            writer.writelines((" ".join(map(str, record)) + "\n").encode()
                              for record in batch[:size * copies])

    rows = []
    for size in SIZES:
        path = paths[size]
        stats = cpu_result(algorithm, path, manifest["source"], oracle, pagerank_oracle,
                           manifest.get("epsilon"))
        records = batch[:size * copies]
        rows.append(dict(name=f"ordinary-{size}", kind="ordinary", graph=identity(path),
                         updates=len(records), logical_insertions=size, batch=records,
                         changed_vertices=stats["changed_vertices"],
                         changed_fraction=stats["changed_vertices"] / actual_vertices,
                         updated_sources=len({src for src, _, _, _ in records}),
                         cpu=stats))
        print(algorithm, size, stats["changed_vertices"], flush=True)
    manifest.update(points=rows, original=identity(base), seed=seed,
                    actual_vertices=actual_vertices,
                    vertex_denominator="real SNAP vertices (no missing ID slots)")
    save(output / "workloads.json", manifest)
    columns = ("name", "logical_insertions", "updates", "updated_sources",
               "changed_vertices", "changed_fraction")
    with (output / "cpu_impact.csv").open("w", newline="") as stream:
        writer = csv.DictWriter(stream, columns, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


def controlled_sssp(base, output, oracle, actual_vertices):
    manifest = json.loads(base.read_text())
    original, = manifest["points"]
    graph = Path(original["graph"]["path"])
    if manifest["algorithm"] != "weighted_sssp" or identity(graph) != original["graph"]:
        raise ValueError("controlled SSSP requires the frozen weighted RN input")
    candidates = subprocess.check_output(
        [oracle, "sssp-probe", graph, str(manifest["source"])], text=True, timeout=600)
    output.mkdir(parents=True, exist_ok=False)
    rows = []
    for line in candidates.splitlines():
        target, src, dst, weight, expected = map(int, line.split())
        name = f"target-vertices-{target}"
        path = output / f"{name}.graph"
        with graph.open("rb") as source, path.open("xb") as writer:
            next(source)
            writer.write(f'{manifest["vertices"]} {manifest["edges"]} 1\n'.encode())
            for _ in range(manifest["edges"]):
                writer.write(next(source))
            writer.write(f"{src} {dst} {weight} 1\n".encode())
        stats = cpu_result("weighted_sssp", path, manifest["source"], oracle, None, None)
        if stats["changed_vertices"] != expected:
            raise ValueError("candidate search disagrees with Dijkstra")
        rows.append(dict(name=name, kind="controlled", graph=identity(path), updates=1,
                         logical_insertions=1, batch=[[src, dst, weight, 1]],
                         target_vertices=target, changed_vertices=expected,
                         changed_fraction=expected / actual_vertices, updated_sources=1, cpu=stats))
        print(name, expected, flush=True)
    manifest.update(points=rows, original=identity(base), actual_vertices=actual_vertices,
                    vertex_denominator="real SNAP vertices (no missing ID slots)")
    save(output / "workloads.json", manifest)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("base", "output", "oracle", "pagerank_oracle"):
        parser.add_argument(name, type=Path)
    parser.add_argument("--seed", type=int, default=SEED)
    parser.add_argument("--actual-vertices", type=int, default=1_965_206)
    parser.add_argument("--controlled-sssp", action="store_true")
    args = parser.parse_args()
    if args.controlled_sssp:
        controlled_sssp(args.base, args.output, args.oracle, args.actual_vertices)
    else:
        prepare(args.base, args.output, args.oracle, args.pagerank_oracle, args.seed,
                args.actual_vertices)
