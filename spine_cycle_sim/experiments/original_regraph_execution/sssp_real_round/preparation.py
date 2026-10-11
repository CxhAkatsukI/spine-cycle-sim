"""Preserve author DBG/tasks while overlaying a common weighted SSSP problem."""

from __future__ import annotations

import heapq
from pathlib import Path
import shutil
import struct

from spine_cycle_sim.experiments.shared_workloads import SliceGraph

INFINITY = 0x7FFFFFFE
ACTIVE = 0x80000000


def read_words(path: Path) -> list[int]:
    payload = path.read_bytes()
    if len(payload) % 4:
        raise ValueError("unaligned u32 capture")
    return list(struct.unpack(f"<{len(payload) // 4}I", payload))


def write_words(path: Path, words: list[int]) -> None:
    with path.open("xb") as stream:
        stream.write(struct.pack(f"<{len(words)}I", *words))


def distances(vertices: int, edges: dict[tuple[int, int], int], root: int) -> list[int]:
    adjacency = [[] for _ in range(vertices)]
    for (src, dst), weight in edges.items():
        adjacency[src].append((dst, weight))
    state = [INFINITY] * vertices
    state[root] = 0
    queue = [(0, root)]
    while queue:
        distance, src = heapq.heappop(queue)
        if distance != state[src]:
            continue
        for dst, weight in adjacency[src]:
            candidate = distance + weight
            if candidate < state[dst]:
                state[dst] = candidate
                heapq.heappush(queue, (candidate, dst))
    return state


def overlay(graph: SliceGraph, capture: Path, layout: dict, target: Path, mode: str) -> dict:
    if mode not in {"cold", "warm_update", "inactive"}:
        raise ValueError("unknown resident state scenario")
    mapping = read_words(capture / "original_to_reordered.u32le")
    if len(mapping) != graph.vertices or sorted(mapping) != list(range(graph.vertices)):
        raise ValueError("author DBG mapping is not a vertex permutation")
    original = {}
    for edge in graph.records:
        key = (mapping[edge.src], mapping[edge.dst])
        if edge.diff != 1 or not 0 < edge.weight <= 4079 or key in original:
            raise ValueError("control needs unique positive weighted edges, not a multigraph")
        original[key] = edge.weight
    summary = layout["summary"]
    if (summary["vertices"], summary["logical_edges"]) != (graph.vertices, len(original)):
        raise ValueError("author graph geometry differs from source slice")
    # The warm problem changes only outgoing weights of original source 0.
    # Its old state is genuinely converged on the old (weight+16) graph.
    root = mapping[0]
    old_edges = {key: weight + 16 for key, weight in original.items()}
    edges = original if mode == "cold" else {
        key: weight if key[0] == root else weight + 16 for key, weight in original.items()}
    state = ([0 if v == root else INFINITY for v in range(graph.vertices)] if mode == "cold"
             else distances(graph.vertices, old_edges, root))
    if mode != "inactive":
        state[root] |= ACTIVE
    state += [0] * (summary["aligned_vertices"] - graph.vertices)
    offsets = read_words(capture / "csr_offsets.u32le")
    destinations = read_words(capture / "csr_destinations.u32le")
    weights = []
    remaining = dict(edges)
    for src in range(graph.vertices):
        for dst in destinations[offsets[src]:offsets[src + 1]]:
            weights.append(remaining.pop((src, dst)))
    if remaining:
        raise ValueError("author CSR omitted a logical pair")
    tasks = read_words(capture / "tasks.u32le")
    weighted = list(tasks)
    remaining = dict(edges)
    descriptor = [0x3447524F, 1, graph.vertices, len(edges), summary["aligned_vertices"],
                  summary["partitions"] * 65536, len(layout["tasks"]), summary["partitions"]]
    for task in layout["tasks"]:
        if task["kind"] != "dense":
            raise ValueError("A4 control requires author dense tasks")
        descriptor += [task[key] for key in ("partition", "subpartition", "kernel", "dst_offset",
                                             "dst_len", "offset_words", "words")] + [0]
        for index in range(task["offset_words"], task["offset_words"] + task["words"], 2):
            src, dst = tasks[index] & 0x7FFFFFFF, tasks[index + 1]
            if dst & ACTIVE:
                continue
            weight = remaining.pop((src, dst))
            local = dst - task["dst_offset"]
            if not 0 <= local < 65536:
                raise ValueError("author task destination outside partition")
            weighted[index + 1] = local | (weight << 19)
    if remaining:
        raise ValueError("author task multiset differs from weighted CSR")
    target.mkdir(parents=True, exist_ok=False)
    for name in ("tasks.u32le", "initial.u32le", "degrees.u32le", "csr_offsets.u32le", "csr_destinations.u32le"):
        shutil.copyfile(capture / name, target / name)
    write_words(target / "execution.u32le", descriptor)
    write_words(target / "sssp_tasks.u32le", weighted)
    write_words(target / "sssp_initial.u32le", state)
    write_words(target / "sssp_weights.u32le", weights)
    return {"mode": mode, "vertices": graph.vertices, "logical_edges": len(edges),
            "padded_vertices": summary["aligned_vertices"], "partitions": summary["partitions"],
            "root_reordered": root, "active_initial": int(mode != "inactive"),
            "changed_weights": sum(src == root for src, _ in edges) if mode == "warm_update" else 0,
            "old_state_converged": mode != "cold", "rounds": 1,
            "convergence_comparison": False, "weighted_task_multiset_verified": True}
