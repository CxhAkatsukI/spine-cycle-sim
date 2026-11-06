"""Freeze PR spread sweeps using the host-compatible FP32 oracle."""

import argparse
import json
from pathlib import Path
import random
import subprocess

from ...original_regraph_execution.hardware.source_retention.runtime import identity, save
from .sssp import Graph, TARGETS, ordinary


def hub_batches(graph, counts, seed):
    hubs = sorted(range(graph.vertices), key=lambda src: (-len(graph.adjacency[src]), src))[:256]
    seen = {(src, dst) for src, dst, _ in graph.edges}
    rng = random.Random(seed)
    batch = []
    for count in counts:
        while len(batch) < count:
            src = hubs[len(batch) % len(hubs)]
            dst = rng.randrange(graph.vertices)
            if src == dst or (src, dst) in seen:
                continue
            seen.add((src, dst))
            batch.append((src, dst, 1))
        yield count, batch.copy()


def fan_in_batches(graph, counts, seed):
    # Two low-degree sources share each destination, so corrections can add up.
    vertices = sorted(range(graph.vertices), key=lambda src: (len(graph.adjacency[src]), src))
    rng = random.Random(seed)
    pool = vertices[:max(3, len(vertices) * 3 // 4)]
    rng.shuffle(pool)
    seen = {(src, dst) for src, dst, _ in graph.edges}
    batch, cursor = [], 0
    for count in counts:
        while len(batch) < count:
            if cursor + 3 > len(pool):
                raise ValueError("fan-in exhausted disjoint source/destination triples")
            left, right, dst = pool[cursor:cursor + 3]
            cursor += 3
            if (left, dst) in seen or (right, dst) in seen:
                continue
            for src in (left, right):
                seen.add((src, dst))
                batch.append((src, dst, 1))
        yield len(batch), batch.copy()


def prepare(args):
    args.output.mkdir(parents=True, exist_ok=False)
    graph = Graph.load(args.graph)
    counts = (2, 4, 8, 16, 32, 64, 128, 256, 512, 1024, 4096, 16384, 65536, 131072)
    generator = hub_batches if args.strategy == "hub" else fan_in_batches
    candidates = [(f"{args.strategy}-{count}", "target-candidate", batch)
                  for count, batch in generator(graph, counts, args.seed)]
    candidates += [(f"ordinary-{count}", "ordinary", ordinary(graph, count, args.seed + count))
                   for count in (8, 64, 512, 4096)]
    manifest = dict(algorithm="residual_pagerank", dataset=args.dataset, source=0,
                    vertices=graph.vertices, edges=len(graph.edges), original=identity(args.graph),
                    oracle=identity(args.oracle), preparation=identity(__file__), epsilon=args.epsilon, points=[],
                    context=dict(seed=args.seed, strategy=args.strategy, old_rank_rounds=128, damping=.85,
                                 max_propagation_rounds=256, threshold_semantics="direct_per_vertex",
                                 vertex_denominator="all_declared_vertices_including_isolated_ids",
                                 changed_semantics="final_fp32_rank_differs_from_old_fp32_rank"))
    for name, kind, batch in candidates:
        path = args.output / (name + ".graph")
        graph.write(path, batch)
        result = subprocess.run([str(args.oracle), str(path), str(args.epsilon)],
                                capture_output=True, text=True, timeout=600)
        (args.output / (name + ".oracle.stdout.json")).write_text(result.stdout)
        (args.output / (name + ".oracle.stderr.txt")).write_text(result.stderr)
        if result.returncode:
            raise RuntimeError("CPU PR reference failed: " + name)
        stats = json.loads(result.stdout)
        if not stats["converged"]:
            raise ValueError("non-converged CPU PR label")
        row = dict(name=name, kind=kind, graph=identity(path), updates=len(batch), **stats,
                   changed_fraction=stats["changed_vertices"] / graph.vertices,
                   cpu_reference="fp32_128_old_rounds_then_thresholded_new_correction_to_convergence")
        manifest["points"].append(row)
        save(args.output / "workloads.json", manifest)
        print(name, row["changed_fraction"], stats["rounds"], flush=True)
    for row in manifest["points"]:
        row["nearest_target_fraction"] = min(TARGETS, key=lambda target: abs(target - row["changed_fraction"]))
    save(args.output / "workloads.json", manifest)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("graph", "oracle", "output"):
        parser.add_argument("--" + name, type=Path, required=True)
    parser.add_argument("--dataset", required=True)
    parser.add_argument("--seed", type=int, default=20261106)
    parser.add_argument("--epsilon", type=float, default=1e-6)
    parser.add_argument("--strategy", choices=("hub", "fan-in"), default="hub")
    prepare(parser.parse_args())


if __name__ == "__main__":
    main()
