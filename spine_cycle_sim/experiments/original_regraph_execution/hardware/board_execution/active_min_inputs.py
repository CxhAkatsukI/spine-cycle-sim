"""Derive active-min resident component fixtures from frozen A4 graph captures."""

import argparse
from array import array
from pathlib import Path
import shutil
import sys

from .. import artifact, oracle
from ..source_build.snapshot import unchanged
from ..source_retention.runtime import save
from . import active_min

ACTIVE = 1 << 31
INFINITY = ACTIVE - 2
PADDING = (1 << 32) - 1
PARTITION = 65536
GUARD = (0xA55A5AA5,) * 16


def weight(source, target):
    return 1 + ((31 * source + 17 * target) & 15)


def write_words(path, words):
    if sys.byteorder != "little":
        words = array("I", words)
        words.byteswap()
    with path.open("xb") as stream:
        words.tofile(stream)


def read_geometry(directory):
    path = directory / "execution.u32le"
    size = path.stat().st_size
    if size % 4 or not 8 * 4 <= size <= (8 + 8 * 4 * 255) * 4:
        raise ValueError("invalid A4 descriptor extent")
    desc = oracle.read_words(path, size // 4)
    magic, version, vertices, edges, aligned, published, tasks, partitions = desc[:8]
    if (magic != 0x3447524F or version != 1 or not 0 < partitions <= 255 or
            not aligned - PARTITION < vertices <= aligned == published == partitions * PARTITION or
            not 0 < edges <= 2**26 or not 0 < tasks <= 4 * partitions or len(desc) != 8 + 8 * tasks):
        raise ValueError("A4 active-min requires all aligned vertices to be published")
    return vertices, edges, aligned, desc


def csr_overlay(directory, vertices, edges, frontier):
    offsets = oracle.read_words(directory / "csr_offsets.u32le", vertices + 1)
    targets = oracle.read_words(directory / "csr_destinations.u32le", edges)
    if offsets[0] or offsets[-1] != edges:
        raise ValueError("invalid CSR endpoints")
    weights = array("I")
    seed, best, sssp_changes = None, 0, 0
    reached = bytearray(vertices) if frontier == "odd-vertices" else None
    for source in range(vertices):
        begin, end = offsets[source], offsets[source + 1]
        if not begin <= end <= edges:
            raise ValueError("invalid CSR row bounds")
        row = targets[begin:end]
        if len(row) != len(set(row)) or any(target >= vertices for target in row):
            raise ValueError("duplicate edge or invalid destination in CSR")
        weights.extend(weight(source, target) for target in row)
        if reached is not None:
            if source % 2:
                for target in row:
                    if target % 2 == 0:
                        reached[target] = 1
            continue
        improvements = sum(target not in (0, source) for target in row)
        if improvements > best:
            seed, best = source, improvements
            sssp_changes = sum(target != source for target in row)
    if reached is not None:
        sssp_changes = sum(reached)
        best = sssp_changes - reached[0]
    if not best or not sssp_changes:
        raise ValueError("fixture would not exercise strict improvement in both policies")
    return seed, {"cc": best, "weighted_sssp": sssp_changes}, weights


def task_overlay(directory, vertices, edges, desc):
    path = directory / "tasks.u32le"
    size = path.stat().st_size
    if size % 8 or not edges * 8 <= size <= 2**30:
        raise ValueError("invalid A4 physical edge extent")
    words = oracle.read_words(path, size // 4)
    cursor = logical = 0
    for i in range(8, len(desc), 8):
        _, _, lane, destination, span, offset, count, reserved = desc[i:i + 8]
        if (lane >= 4 or reserved or offset != cursor or not count or count % 16 or
                offset + count > len(words) or not 0 < span <= PARTITION):
            raise ValueError("invalid author task bounds")
        for j in range(offset, offset + count, 2):
            target = words[j + 1]
            if target == PADDING:
                continue
            source = words[j] & (ACTIVE - 1)
            if not source < vertices or not destination <= target < min(vertices, destination + span):
                raise ValueError("edge outside author task domain")
            words[j + 1] = (weight(source, target) << 19) | (target - destination)
            logical += 1
        cursor += count
    if cursor != len(words) or logical != edges:
        raise ValueError("A4 tasks do not cover the declared edge geometry")
    return words


def prepare(source, host, output, *, frontier="single-source"):
    if frontier not in ("single-source", "odd-vertices"):
        raise ValueError("unknown active-min frontier")
    output.mkdir(parents=True, exist_ok=False)
    try:
        report = _prepare(source, host, output, frontier)
    except Exception as error:
        save(output / "manifest.json", {"status": "FAILED_RETAINED", "error": repr(error),
                                       "hardware_timing_measured": False})
        raise
    save(output / "manifest.json", report)
    return report


def _prepare(source, host, output, frontier):
    names = tuple(f"{name}.u32le" for name in active_min.INPUTS)
    pins = [artifact.identity(host), *(artifact.identity(source / name) for name in names)]
    directory = output / "inputs"
    directory.mkdir()
    for name, pin in zip(names, pins[1:]):
        copy = directory / name
        shutil.copyfile(source / name, copy)
        if artifact.identity(copy)["sha256"] != pin["sha256"]:
            raise ValueError("copied author capture differs from source identity")
    vertices, edges, aligned, desc = read_geometry(directory)
    seed, changes_by_algorithm, weights = csr_overlay(directory, vertices, edges, frontier)
    write_words(directory / "sssp_weights.u32le", weights)
    write_words(directory / "sssp_tasks.u32le", task_overlay(directory, vertices, edges, desc))
    cc = array("I", range(vertices)) + array("I", [0]) * (aligned - vertices)
    sssp = array("I", [INFINITY]) * vertices + array("I", [0]) * (aligned - vertices)
    active_vertices = range(1, vertices, 2) if seed is None else (seed,)
    for vertex in active_vertices:
        cc[vertex] = sssp[vertex] = ACTIVE
    write_words(directory / "cc_initial.u32le", cc)
    write_words(directory / "sssp_initial.u32le", sssp)
    inputs = sorted(directory.glob("*.u32le"))
    input_pins = [artifact.identity(path) for path in inputs]
    audits = {}
    for algorithm in active_min.ALGORITHMS:
        destination = output / algorithm
        destination.mkdir()
        geometry, expected, result = active_min.read_offline(host, algorithm, directory, destination)
        if (geometry["vertices"], geometry["logical_edges"], geometry["tasks"]) != (vertices, edges, desc[6]):
            raise ValueError("independent oracle used different input geometry")
        values = oracle.read_words(Path(expected["path"]), aligned + len(GUARD))
        if tuple(values[aligned:]) != GUARD:
            raise ValueError("offline oracle output guard differs")
        changes = sum(bool(value & ACTIVE) for value in memoryview(values)[:aligned])
        if changes != changes_by_algorithm[algorithm]:
            raise ValueError("offline oracle disagrees with the declared strict improvements")
        audits[algorithm] = {"geometry": geometry, "expected": expected, "result": result,
                             "improved_vertices": changes}
    unchanged(pins + input_pins)
    return {"status": "ACTIVE_MIN_COMPONENT_INPUTS_OFFLINE_PASS", "source_pins": pins,
            "input_pins": input_pins, "audits": audits, "seed": seed, "frontier": frontier,
            "initial_active_vertices": len(active_vertices),
            "weight_rule": "1 + ((31 * source + 17 * destination) & 15)",
            "scope": "synthetic resident active state on frozen graph; one superstep, not convergence",
            "hardware_timing_measured": False, "performance_retention_measured": False}


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("source", "host", "output"):
        parser.add_argument("--" + name, type=Path, required=True)
    parser.add_argument("--frontier", choices=("single-source", "odd-vertices"), default="single-source")
    args = parser.parse_args()
    print(prepare(args.source.resolve(), args.host.absolute(), args.output.resolve(),
                  frontier=args.frontier)["status"], flush=True)
