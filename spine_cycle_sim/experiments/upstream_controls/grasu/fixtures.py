"""Independent fixed kernel-ABI fixtures; intentionally not original host preparation."""

import array
import sys

HOT = 131072
HALF = HOT + 32
SEGMENTS = HALF * 2
EMPTY = 0x80000000
NAMES = ("empty", "one", "three", "lane_65", "lane_257", "hot_only", "cold_only", "mixed_three_batches")


def targets():
    return [2 * (row + bank) + half for row in (0, HOT - 16, HOT, HOT + 16)
            for bank in range(16) for half in range(2)]


def batches(case):
    if type(case) is not int or not 0 <= case < len(NAMES): raise ValueError("unknown G fixture")
    selected = targets()
    if case < 4: return [[(segment, 20, False) for segment in selected[:(0, 1, 3, 65)[case]]]]
    if case == 4:
        return [[(segment, delta, False) for delta in (20, 60) for segment in selected] + [(selected[0], 40, True)]]
    if case == 5: selected = [segment for segment in selected if segment // 2 < HOT]
    if case == 6: selected = [segment for segment in selected if segment // 2 >= HOT]
    first = [(segment, delta, deletion) for segment in selected for delta, deletion in ((20, False), (60, False), (40, True))]
    return [first] if case != 7 else [first] + [
        [(segment, delta, deletion) for segment in selected for delta, deletion in operations]
        for operations in (((20, True), (50, False)), ((60, True), (60, False)))]


def source(segment): return int(segment >= HOT * 2)
def base(segment): return (segment - HOT * 2 * source(segment)) * 128
def route(segment): return (segment & 1) * 2 + int(segment // 2 >= HOT)
def edge(item):
    segment, delta, deletion = item
    return (int(deletion) << 63) | (source(segment) << 32) | (base(segment) + delta)


def request_rows(updates):
    """Address/value trace for original binary search, in source harness invocation order."""
    rows = []
    for kernel in range(4):
        for lane in range(64):
            for index in range(kernel + lane * 4, len(updates), 256):
                item = updates[index]; src = source(item[0]); key = edge(item) & ((1 << 63) - 1)
                begin, end = ((0, HOT * 2) if not src else (HOT * 2, SEGMENTS))
                rows.append((kernel, lane, 0, src, ((begin * 16) << 32) | (end * 16)))
                while (mid := (begin + end) // 2) != begin:
                    value = (source(mid) << 32) | (base(mid) + 10)
                    rows.append((kernel, lane, 1, mid, value))
                    if value <= key: begin = mid
                    else: end = mid
                if begin != item[0]: raise ValueError("fixture does not admit source search")
    return rows


def final_state(case):
    result = array.array("I", [EMPTY]) * (SEGMENTS * 16)
    if result.itemsize != 4: raise ValueError("G capture requires 32-bit array words")
    for segment in range(SEGMENTS):
        result[segment * 16:segment * 16 + 3] = array.array("I", (base(segment) + value for value in (10, 40, 70)))
    changes = {}
    for batch in batches(case):
        for segment, delta, deletion in batch:
            values = changes.setdefault(segment, {10, 40, 70})
            if deletion:
                if delta not in values: raise ValueError("absent fixture deletion")
                values.remove(delta)
            else:
                if delta in values or len(values) == 16: raise ValueError("invalid fixture insertion")
                values.add(delta)
    for segment, values in changes.items():
        row = [base(segment) + delta for delta in sorted(values)] + [EMPTY] * (16 - len(values))
        result[segment * 16:(segment + 1) * 16] = array.array("I", row)
    if sys.byteorder != "little": result.byteswap()
    return result.tobytes()
