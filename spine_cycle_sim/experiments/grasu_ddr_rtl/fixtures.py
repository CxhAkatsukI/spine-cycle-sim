"""Post-search cold-region inputs and an independent sorted-set state oracle."""

from pathlib import Path
import struct

EMPTY = 0x80000000
FIRST = 131072
LINES = 32


def updates(sequence):
    repeated = [(0, 20, False), (0, 60, False), (0, 40, True)]
    choices = {"empty": [], "single": repeated[:1], "unique_even": [(i, 20, False) for i in range(0, 32, 2)],
        "unique_both": [(i, 20, False) for i in range(32)], "repeat_even": repeated,
        "repeat_odd": [(1, value, delete) for _, value, delete in repeated],
        "repeat_both": [(i, value, delete) for _, value, delete in repeated for i in (0, 1)],
        "alternating": [(0, 40, True), (0, 20, False), (0, 10, True), (0, 60, False)]}
    if sequence not in choices:
        raise ValueError("unknown original DDR fixture")
    return choices[sequence]


def encode(item):
    line, value, delete = item
    if not 0 <= line < LINES or not 0 < value < 1000 or type(delete) is not bool:
        raise ValueError("invalid original DDR update")
    return (delete << 95) | ((line * 1000 + value) << 32) | ((FIRST + line) * 32)


def state(sequence):
    initial = [[i * 1000 + 10, i * 1000 + 40, i * 1000 + 70] + [EMPTY] * 13 for i in range(LINES)]
    expected = [line.copy() for line in initial]
    for line, value, delete in updates(sequence):
        value += line * 1000
        live = [word for word in expected[line] if word != EMPTY]
        if delete:
            if value not in live:
                raise ValueError("absent fixture deletion")
            live.remove(value)
        else:
            if value in live or len(live) == 16:
                raise ValueError("duplicate/full fixture insertion")
            live.append(value)
        expected[line] = sorted(live) + [EMPTY] * (16 - len(live))
    return initial, expected


def prepare(directory: Path, case):
    directory.mkdir(parents=True, exist_ok=False)
    initial, expected = state(case["sequence"])
    packets = [encode(item) for item in updates(case["sequence"])]
    for name, rows in (("initial", initial), ("expected", expected)):
        data = struct.pack("<512I", *(word for row in rows for word in row))
        (directory / (name + ".u32le")).write_bytes(data)
        (directory / (name + ".hex")).write_text("".join(f"{int.from_bytes(data[i:i+64], 'little'):0128x}\n" for i in range(0, len(data), 64)), encoding="ascii")
    (directory / "updates.u32le").write_bytes(b"".join(value.to_bytes(12, "little") for value in packets))
    (directory / "updates.hex").write_text("".join(f"{value:024x}\n" for value in packets), encoding="ascii")
    return {"updates": len(packets), "insertions": sum(not item[2] for item in updates(case["sequence"])),
            "sequence": case["sequence"], "packets": packets}


def read_hex(path: Path):
    lines = path.read_text(encoding="ascii").splitlines()
    if len(lines) != LINES or any(len(line) != 128 or any(char not in "0123456789abcdefABCDEF" for char in line) for line in lines):
        raise ValueError("RTL complete memory capture malformed or unknown")
    return b"".join(int(line, 16).to_bytes(64, "little") for line in lines)
