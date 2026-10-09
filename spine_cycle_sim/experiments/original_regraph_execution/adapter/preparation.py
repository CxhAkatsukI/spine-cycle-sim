"""Source16 PMA from unchanged admitted A4 tasks; no logical-edge filtering."""

import array
from pathlib import Path
import sys

from spine_cycle_sim.experiments.campaign_runtime import sha256_file

EMPTY = 0x80000000


def load(path: Path):
    if path.stat().st_size % 4 or path.stat().st_size > 512 * 1024**2: raise ValueError("adapter input extent")
    result = array.array("I")
    if result.itemsize != 4: raise ValueError("adapter requires 32-bit array words")
    with path.open("rb") as stream: result.fromfile(stream, path.stat().st_size // 4)
    if sys.byteorder != "little": result.byteswap()
    return result


def save_words(stream, words):
    values = array.array("I", words)
    if sys.byteorder != "little": values.byteswap()
    values.tofile(stream)


def task_layout(vertices, compact, destination):
    if not vertices or not compact or len(compact) % 2: raise ValueError("adapter task extent")
    rows = {}; logical = 0
    for i in range(0, len(compact), 2):
        source, target = compact[i] & 0x7fffffff, compact[i + 1]
        if source >= vertices: raise ValueError("adapter source domain")
        if target & EMPTY: continue
        if not destination <= target < destination + 65536: raise ValueError("adapter task destination domain")
        rows.setdefault(source, []).append(target - destination); logical += 1
    empty_control = not rows
    if empty_control: rows[compact[0] & 0x7fffffff] = []
    bounds = array.array("I"); slots = array.array("I")
    for source in range(vertices):
        begin = len(slots)
        if source in rows:
            values = sorted(rows[source])
            extent = max(16, (len(values) + 15) // 16 * 16)
            slots.extend(values); slots.extend([EMPTY] * (extent - len(values)))
        bounds.extend((len(slots), begin))
    return bounds, slots, logical, int(empty_control)


def prepare(directory: Path):
    descriptor = load(directory / "execution.u32le"); compact = load(directory / "tasks.u32le")
    if len(descriptor) < 8 or tuple(descriptor[:2]) != (0x3447524f, 1) or len(descriptor) != 8 + descriptor[6] * 8:
        raise ValueError("adapter requires exact A4 descriptors")
    vertices = descriptor[2]; tasks = []; row_offset = pma_offset = logical = physical = empty = 0
    with (directory / "rows.u32le").open("xb") as row_file, (directory / "pma.u32le").open("xb") as pma_file:
        for base in range(8, len(descriptor), 8):
            part, subpart, kernel, destination, _, offset, count, reserved = descriptor[base:base + 8]
            if reserved or offset + count > len(compact) or not count or count % 16: raise ValueError("adapter A4 task extent")
            bounds, slots, valid, control = task_layout(vertices, compact[offset:offset + count], destination)
            tasks += [part, subpart, kernel, destination, row_offset, pma_offset, len(slots), control]
            save_words(row_file, bounds); save_words(pma_file, slots)
            row_offset += len(bounds); pma_offset += len(slots); logical += valid; physical += len(slots); empty += control
    if logical != descriptor[3]: raise ValueError("adapter full logical graph changed")
    with (directory / "adapter.u32le").open("xb") as stream:
        save_words(stream, [0x504d4131, 1, vertices, descriptor[6], 131072, row_offset, pma_offset, 0] + tasks)
    return {"vertices": vertices, "tasks": descriptor[6], "logical_edges": logical, "physical_edges": physical,
        "empty_task_controls": empty, "files": [{"name": name, "sha256": sha256_file(directory / name), "bytes": (directory / name).stat().st_size}
            for name in ("adapter.u32le", "rows.u32le", "pma.u32le")]}
