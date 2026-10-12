"""A common full-word PMA that fits dst19 and exercises both hot/cold paths."""

import array
import struct
import sys

from ...upstream_controls.grasu.fixtures import EMPTY, HOT, SEGMENTS

COUNTS = (0, 64, 4096)


def base(segment):
    return (1 << 19) + (segment if segment < HOT * 2 else segment - HOT * 2) * 2


def source(segment):
    return int(segment >= HOT * 2)


def selected(count):
    if count not in COUNTS:
        raise ValueError("undeclared G batch size")
    # Cold capacity is 64 segments; use distinct keys to avoid concurrent conflicts.
    cold = min(count // 2, 64)
    return list(range(count - cold)) + list(range(HOT * 2, HOT * 2 + cold))


def prepare(root, count):
    root.mkdir(parents=True, exist_ok=False)
    words = array.array("I", [EMPTY]) * (SEGMENTS * 16)
    for segment in range(SEGMENTS):
        words[segment * 16] = base(segment)
    tables = array.array("Q", ((source(i) << 32) | base(i) for i in range(SEGMENTS)))
    if words.itemsize != 4 or tables.itemsize != 8:
        raise ValueError("unsupported array ABI")
    if sys.byteorder != "little":
        words.byteswap(); tables.byteswap()
    (root / "initial.u32le").write_bytes(words.tobytes())
    (root / "binary.u64le").write_bytes(tables.tobytes())
    (root / "rows.u64le").write_bytes(struct.pack("<QQ", HOT * 2 * 16,
        ((HOT * 2 * 16) << 32) | (SEGMENTS * 16)))
    operations, changes = [], {}
    for segment in selected(count):
        values = changes.setdefault(segment, {base(segment)})
        target = base(segment) + 1
        deletion = target in values
        (values.remove if deletion else values.add)(target)
        operations.append((int(deletion) << 63) | (source(segment) << 32) | target)
    payload = bytearray(struct.pack("<II", 1, len(operations)))
    payload.extend(struct.pack(f"<{len(operations)}Q", *operations))
    payload.extend(struct.pack("<I", len(changes)))
    for segment, values in sorted(changes.items()):
        row = sorted(values) + [EMPTY] * (16 - len(values))
        payload.extend(struct.pack("<17I", segment, *row))
    (root / "batches.bin").write_bytes(payload)
