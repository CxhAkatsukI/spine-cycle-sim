"""Exact positive-integer SSSP reference and insertion-only batch construction."""

from dataclasses import dataclass
import heapq
import math
from pathlib import Path
import random


TARGETS = (0.00001, 0.0001, 0.001, 0.01, 0.1, 0.5)
INF = math.inf


@dataclass
class Graph:
    vertices: int
    edges: list
    adjacency: list

    @classmethod
    def load(cls, path):
        with Path(path).open() as stream:
            vertices, count, updates = map(int, next(stream).split())
            if vertices <= 0 or count <= 0 or updates < 0:
                raise ValueError("invalid dynamic graph header")
            edges, adjacency, seen = [], [[] for _ in range(vertices)], set()
            for _ in range(count):
                src, dst, weight = map(int, next(stream).split())
                if not (0 <= src < vertices and 0 <= dst < vertices and 1 <= weight <= 4095):
                    raise ValueError("edge outside weight12 or vertex ABI")
                if (src, dst) in seen:
                    raise ValueError("duplicate old edge")
                seen.add((src, dst))
                edges.append((src, dst, weight))
                adjacency[src].append((dst, weight))
            for _ in range(updates):
                if len(next(stream).split()) != 4:
                    raise ValueError("invalid original update")
            if stream.read().strip():
                raise ValueError("unexpected graph trailer")
        return cls(vertices, edges, adjacency)

    def write(self, path, batch):
        with Path(path).open("x") as stream:
            stream.write(f"{self.vertices} {len(self.edges)} {len(batch)}\n")
            for src, dst, weight in self.edges:
                stream.write(f"{src} {dst} {weight}\n")
            for src, dst, weight in batch:
                stream.write(f"{src} {dst} {weight} 1\n")


def relax(adjacency, distance, seeds, *, max_changes=None):
    queue = []
    changed = set()
    previous = {}

    def assign(vertex, value):
        if max_changes is not None:
            previous.setdefault(vertex, distance[vertex])
        distance[vertex] = value
        changed.add(vertex)
        heapq.heappush(queue, (value, vertex))

    for vertex, value in seeds:
        if value < distance[vertex]:
            assign(vertex, value)
    while queue:
        if max_changes is not None and len(changed) > max_changes:
            for vertex, value in previous.items():
                distance[vertex] = value
            return None
        value, src = heapq.heappop(queue)
        if distance[src] != value:
            continue
        for dst, weight in adjacency[src]:
            candidate = value + weight
            if candidate < distance[dst]:
                assign(dst, candidate)
    return changed


def distances(graph, source, batch=()):
    if not 0 <= source < graph.vertices:
        raise ValueError("source outside graph")
    adjacency = [list(row) for row in graph.adjacency]
    for src, dst, weight in batch:
        adjacency[src].append((dst, weight))
    result = [INF] * graph.vertices
    relax(adjacency, result, [(source, 0)])
    return result


def ordinary(graph, count, seed):
    rng = random.Random(seed)
    seen = {(src, dst) for src, dst, _ in graph.edges}
    batch = []
    while len(batch) < count:
        src, dst = rng.randrange(graph.vertices), rng.randrange(graph.vertices)
        if src != dst and (src, dst) not in seen:
            seen.add((src, dst))
            batch.append((src, dst, rng.randrange(1, 65)))
    return batch


def construct(graph, source, *, seed=20261106, max_updates=131072, targets=TARGETS, include_ordinary=True):
    """Select by CPU impact alone; FPGA timing never participates in selection."""
    old = distances(graph, source)
    existing = {dst for dst, _ in graph.adjacency[source]}
    eligible = [v for v in range(graph.vertices) if v != source and v not in existing and old[v] > 1]
    rng = random.Random(seed)
    hubs = sorted(eligible, key=lambda v: (-len(graph.adjacency[v]), v))[:32]
    probes = list(dict.fromkeys(hubs + rng.sample(eligible, min(64, len(eligible)))))
    trials = []
    for dst in probes:
        weights = {1}
        if math.isfinite(old[dst]):
            weights.update(min(4095, max(1, int(old[dst] * share))) for share in (.25, .5, .75, .95))
        for weight in sorted(weights):
            state = old.copy()
            count = len(relax(graph.adjacency, state, [(dst, weight)]))
            trials.append((count, dst, weight))
    rows = []
    shuffled = eligible.copy()
    rng.shuffle(shuffled)
    if any(not 0 < target <= 1 for target in targets):
        raise ValueError("target fractions must be in (0, 1]")
    for target in targets:
        wanted = max(1, math.ceil(graph.vertices * target))
        below = [trial for trial in trials if trial[0] <= wanted]
        chosen = max(below, default=(0, None, 1))
        state, affected, batch = old.copy(), set(), []
        order = ([(chosen[1], chosen[2])] if chosen[1] is not None else [])
        order += [(vertex, 1) for vertex in shuffled]
        used = set()
        for dst, weight in order:
            if len(affected) >= wanted or len(batch) >= max_updates:
                break
            if dst in used or state[dst] <= 1:
                continue
            remaining = max(1, wanted - len(affected))
            changed = relax(graph.adjacency, state, [(dst, weight)],
                            max_changes=remaining + math.ceil(wanted * .1))
            if changed is None:
                continue
            used.add(dst)
            batch.append((source, dst, weight))
            affected.update(changed)
        if batch:
            # Independent from-scratch oracle checks the incremental constructor.
            expected = distances(graph, source, batch)
            if expected != state:
                raise ValueError("incremental CPU reference differs from full Dijkstra")
            rows.append(dict(name=f"target-{target:g}", kind="target", target_fraction=target,
                             changed_vertices=len(affected), batch=batch,
                             target_reached=len(affected) >= wanted))
    for count in ((8, 64, 512, 4096) if include_ordinary else ()):
        batch = ordinary(graph, count, seed + count)
        final = distances(graph, source, batch)
        rows.append(dict(name=f"ordinary-{count}", kind="ordinary", target_fraction=None,
                         changed_vertices=sum(a != b for a, b in zip(old, final)), batch=batch))
    return rows, dict(old_reachable_vertices=sum(math.isfinite(d) for d in old),
                      probe_count=len(trials), seed=seed, max_updates=max_updates, requested_targets=targets,
                      vertex_denominator="all_declared_vertices_including_isolated_ids")
