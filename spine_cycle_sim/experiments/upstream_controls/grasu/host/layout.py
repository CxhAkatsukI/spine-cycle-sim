"""Independent permutation, reservation, compaction and per-update state oracle."""

import array
from bisect import bisect_right
from collections import Counter
from pathlib import Path
import sys

from .fixtures import read

EMPTY = 1 << 63
HOT = 131072


def words(path: Path, width: int, count: int):
    if path.stat().st_size != width * count or width * count > 64 * 1024**2: raise ValueError("G host capture extent: " + path.name)
    result = array.array("I" if width == 4 else "Q")
    if result.itemsize != width: raise ValueError("G host requires 32/64-bit array words")
    with path.open("rb") as stream: result.fromfile(stream, count)
    if sys.byteorder != "little": result.byteswap()
    return result


def route(segment): return (segment & 1) * 2 + int(segment // 2 >= HOT)


def locate(binary, offsets, edge):
    edge &= EMPTY - 1; source = edge >> 32
    begin, end = offsets[source] // 16, offsets[source + 1] // 16
    position = bisect_right(binary, edge, begin, end)
    if position == begin: raise ValueError("G update outside prepared row")
    return position - 1


def verify(input_path: Path, directory: Path):
    vertices, initial, updates, final_edges = read(input_path)
    mapping = words(directory / "mapping.u32le", 4, vertices)
    if len(set(mapping)) != vertices or max(mapping) >= vertices: raise ValueError("G mapping not a permutation")
    inverse = [0] * vertices
    for old, new in enumerate(mapping): inverse[new] = old
    mapped_initial = array.array("Q", ((mapping[s] << 32) | mapping[d] for s, d in initial))
    mapped_updates = array.array("Q", ((mapping[s] << 32) | mapping[d] | (EMPTY if not op else 0) for s, d, op in updates))
    if words(directory / "mapped_initial.u64le", 8, len(initial)) != mapped_initial: raise ValueError("G mapped initial mismatch")
    if words(directory / "mapped_updates.u64le", 8, len(updates)) != mapped_updates: raise ValueError("G mapped updates mismatch")
    present = set(mapped_initial)
    union = sorted(present | {edge for edge in mapped_updates if edge < EMPTY})
    degree = Counter(edge >> 32 for edge in union); frequency = Counter(s for s, _, _ in updates)
    offsets = array.array("Q", [0]); previous = None
    for vertex in range(vertices):
        count = (degree[vertex] + 15) // 16
        priority = (frequency[inverse[vertex]], count) if count else (-1, 1)
        if previous is not None and previous[0] * priority[1] < priority[0] * previous[1]: raise ValueError("G priority order mismatch")
        previous = priority; offsets.append(offsets[-1] + count * 16)
    if words(directory / "row_offsets.u64le", 8, vertices + 1) != offsets: raise ValueError("G reservation offsets mismatch")
    prepared = array.array("Q"); binary = array.array("Q"); empty = full = maximum = position = 0
    for vertex in range(vertices):
        row = union[position:position + degree[vertex]]; position += len(row)
        for first in range(0, len(row), 16):
            chunk = row[first:first + 16]; live = [edge for edge in chunk if edge in present]
            binary.append(chunk[0]); prepared.extend(live + [EMPTY] * (16 - len(live)))
            empty += not live; full += len(live) == 16; maximum = max(maximum, len(live))
    if words(directory / "binary.u64le", 8, len(binary)) != binary: raise ValueError("G future-union search heads mismatch")
    if words(directory / "prepared.u64le", 8, len(prepared)) != prepared: raise ValueError("G prepared PMA mismatch")
    updated = array.array("Q", prepared); routes = [0] * 4
    for edge in mapped_updates:
        segment = locate(binary, offsets, edge); routes[route(segment)] += 1
        values = [value for value in updated[segment * 16:(segment + 1) * 16] if value != EMPTY]
        target = edge & (EMPTY - 1)
        if edge & EMPTY:
            if target not in values: raise ValueError("G mapped deletion absent")
            values.remove(target)
        else:
            if target in values or len(values) == 16: raise ValueError("G mapped insertion invalid")
            values.append(target); values.sort()
        maximum = max(maximum, len(values))
        updated[segment * 16:(segment + 1) * 16] = array.array("Q", values + [EMPTY] * (16 - len(values)))
    if words(directory / "updated.u64le", 8, len(updated)) != updated: raise ValueError("G complete updated PMA mismatch")
    if sum(value != EMPTY for value in updated) != len(final_edges): raise ValueError("G final edge count mismatch")
    segments = len(binary)
    checked = 2 * 16 * (max(HOT, (segments + 1) // 2) + max(HOT, segments // 2))
    facts = {"vertices": vertices, "initial_edges": len(initial), "updates": len(updates), "final_edges": len(final_edges),
        "segments": segments, "route_updates": routes, "empty_initial_segments": empty, "full_initial_segments": full,
        "max_occupancy": maximum, "checked_device_slots": checked, "defined_padding_bytes": (checked - len(prepared) * 2) * 4}
    return facts, binary, offsets, mapped_updates, sum(op for _, _, op in updates)
