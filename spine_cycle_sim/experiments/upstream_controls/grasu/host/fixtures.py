"""Fixed graph/update inputs in the original GraSU text format."""

from pathlib import Path

NAMES = ("empty_graph", "empty_batch", "insertion_only", "full_delete", "mixed_reservation", "hot_skew", "same_segment", "threshold_ring")


def fixture(name):
    if name == "empty_graph": return 8, [], []
    if name == "empty_batch": return 64, [(v, (v + 1) % 32) for v in range(32)], []
    if name == "insertion_only": return 64, [], [(0, v, 1) for v in range(32)]
    if name == "full_delete": return 64, [(0, v) for v in range(32)], [(0, v, 0) for v in range(32)]
    if name == "mixed_reservation":
        return 96, [(s, 32 + 8 * s + i) for s in range(8) for i in range(8)], [
            item for s in range(8) for item in [(s, 8 * s + i, 1) for i in range(8)] + [(s, 32 + 8 * s + i, 0) for i in range(2)]]
    if name == "hot_skew":
        initial = [(s, (s * 13 + i) % 128) for s in range(8) for i in range(s + 2)]
        present = set(initial); updates = []
        for s in range(8):
            updates += [(s, v, 1) for v in [v for v in range(128) if (s, v) not in present][:s + 1]]
            updates += [(s, (s * 13) % 128, 0)]
        return 128, initial, updates
    if name == "same_segment":
        return 32, [(0, v) for v in (1, 2, 3)], [(0, 4, op) for _ in range(30) for op in (1, 0)] + [(0, 2, 0), (0, 5, 1)]
    if name == "threshold_ring":
        n = 262208
        return n, [(v, (v + 1) % n) for v in range(n)], [(v, v, 1) for v in range(n)]
    raise ValueError("unknown G host fixture")


def write(name: str, path: Path):
    vertices, initial, updates = fixture(name)
    with path.open("x", encoding="ascii") as stream:
        stream.write(f"{vertices} {len(initial)} {len(updates)}\n")
        for source, destination in initial: stream.write(f"{source} {destination}\n")
        for source, destination, operation in updates: stream.write(f"{source} {destination} {operation}\n")


def read(path: Path):
    with path.open(encoding="ascii") as stream:
        header = stream.readline().split()
        if len(header) != 3: raise ValueError("G host header fields")
        vertices, old, count = map(int, header)
        if not 0 < vertices <= 262208 or not 0 <= old <= 524416 or not 0 <= count <= 524416: raise ValueError("G host header domain")
        initial, updates = [], []
        for index in range(old + count):
            fields = stream.readline().split()
            if len(fields) != (2 if index < old else 3): raise ValueError("G host row extent")
            values = tuple(map(int, fields))
            if not 0 <= values[0] < vertices or not 0 <= values[1] < vertices: raise ValueError("G host vertex domain")
            if index < old: initial.append(values)
            elif values[2] not in (0, 1): raise ValueError("G host operation domain")
            else: updates.append(values)
        if stream.read().strip(): raise ValueError("G host trailing rows")
    present = set(initial)
    if len(present) != len(initial): raise ValueError("G host initial duplicate")
    for s, d, op in updates:
        if op:
            if (s, d) in present: raise ValueError("G host duplicate insertion")
            present.add((s, d))
        else:
            if (s, d) not in present: raise ValueError("G host absent deletion")
            present.remove((s, d))
    return vertices, initial, updates, present
