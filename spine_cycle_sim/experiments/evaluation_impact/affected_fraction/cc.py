"""Canonical-minimum connected-component labels and reciprocal insertions."""

import math
import random
from itertools import chain

from .sssp import TARGETS


def labels(graph, batch=()):
    parent = list(range(graph.vertices))

    def root(vertex):
        while parent[vertex] != vertex:
            parent[vertex] = parent[parent[vertex]]
            vertex = parent[vertex]
        return vertex

    for src, dst, _ in chain(graph.edges, batch):
        left, right = root(src), root(dst)
        if left != right:
            parent[max(left, right)] = min(left, right)
    return [root(vertex) for vertex in range(graph.vertices)]


def reciprocal_ordinary(graph, count, seed):
    rng = random.Random(seed)
    seen = {(src, dst) for src, dst, _ in graph.edges}
    batch = []
    while len(batch) < count * 2:
        src, dst = rng.randrange(graph.vertices), rng.randrange(graph.vertices)
        if src == dst or (src, dst) in seen or (dst, src) in seen:
            continue
        weight = rng.randrange(1, 65)
        for left, right in ((src, dst), (dst, src)):
            seen.add((left, right))
            batch.append((left, right, weight))
    return batch


def construct(graph, *, seed=20261106, max_updates=131072):
    old = labels(graph)
    components = {}
    for vertex, label in enumerate(old):
        components.setdefault(label, []).append(vertex)
    rows = []
    for target in TARGETS:
        rng = random.Random(seed)
        wanted = max(1, math.ceil(graph.vertices * target))
        # Minimum-ID anchor never relabels vertices that already joined it.
        anchor = list(components[0])
        candidates = [(len(vertices), label) for label, vertices in components.items() if label != 0]
        candidates.sort(reverse=True)
        batch, count = [], 0
        for size, label in candidates:
            if count >= wanted or len(batch) + 2 > max_updates:
                break
            if count + size > wanted + math.ceil(wanted * .1):
                continue
            left, right = rng.choice(anchor), rng.choice(components[label])
            batch.extend(((left, right, 1), (right, left, 1)))
            anchor.extend(components[label])
            count += size
        if batch:
            final = labels(graph, batch)
            actual = sum(left != right for left, right in zip(old, final))
            if actual != count:
                raise ValueError("incremental CC selection differs from full union-find")
            rows.append(dict(name=f"target-{target:g}", kind="target", target_fraction=target,
                             target_reached=actual >= wanted, changed_vertices=actual, batch=batch))
    for count in (8, 64, 512, 4096):
        batch = reciprocal_ordinary(graph, count, seed + count)
        final = labels(graph, batch)
        rows.append(dict(name=f"ordinary-{count}", kind="ordinary", target_fraction=None,
                         requested_undirected_insertions=count, batch=batch,
                         changed_vertices=sum(left != right for left, right in zip(old, final))))
    return rows, dict(components=len(components), largest_component=max(map(len, components.values())),
                      seed=seed, max_updates=max_updates,
                      vertex_denominator="all_declared_vertices_including_isolated_ids")
