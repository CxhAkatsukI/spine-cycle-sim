"""Predeclared capacity-safe neighbors and same-key ordering stress."""

from ..preparation import HOT, prepare_segments

CASES = (
    ("empty", 0, "mixed"), ("one", 1, "mixed"), ("three", 3, "mixed"),
    ("lane_boundary", 16, "hot"), ("cold_boundary", 65, "cold"),
    ("small", 64, "mixed"), ("hot_small", 64, "hot"),
    ("cold_small", 64, "cold"), ("neighbor", 257, "mixed"),
    ("large", 4096, "mixed"), ("larger", 8192, "mixed"),
    ("same_key", 257, "conflict"),
    ("amortized", 16384, "mixed"), ("amortized_large", 65536, "mixed"),
)


def segments(count, kind):
    if kind == "hot":
        return list(range(count))
    if kind == "cold":
        return [HOT * 2 + i % 64 for i in range(count)]
    if kind == "mixed":
        cold = min(count // 2, 64)
        return list(range(count - cold)) + list(range(HOT * 2, HOT * 2 + cold))
    if kind == "conflict":
        return [0] * count
    raise ValueError("unknown G neighbor kind")


def prepare(root):
    for name, count, kind in CASES:
        prepare_segments(root / name, segments(count, kind))
