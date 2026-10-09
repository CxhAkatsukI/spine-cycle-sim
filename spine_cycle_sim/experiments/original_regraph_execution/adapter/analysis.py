"""Independent full edge-multiset, PMA layout and emitted-packet admission."""

import json
from pathlib import Path
import struct

from spine_cycle_sim.experiments.campaign_runtime import sha256_file
from spine_cycle_sim.experiments.upstream_controls.grasu.analysis import unique_fields
from .preparation import EMPTY, load

STATUS = "ADAPTER_SOURCE_FUNCTIONAL_PASS_NOT_FINITE_TIMING"


def inspect(directory: Path, capture: Path | None = None):
    original = load(directory / "execution.u32le"); compact = load(directory / "tasks.u32le")
    descriptor = load(directory / "adapter.u32le"); rows = load(directory / "rows.u32le"); pma = load(directory / "pma.u32le")
    vertices, count = original[2], original[6]
    if (list(descriptor[:8]) != [0x504d4131, 1, vertices, count, 131072, len(rows), len(pma), 0] or
            len(descriptor) != 8 + count * 8 or len(rows) != vertices * count * 2): raise ValueError("adapter descriptor/row extent")
    position = logical = physical = empty = duplicates = 0; reads = [0] * 4
    stream = capture.open("rb") if capture is not None else None
    try:
        for ordinal in range(count):
            base = 8 + ordinal * 8
            partition, subpartition, kernel, destination, row_offset, pma_offset, slots, control = descriptor[base:base + 8]
            task = original[base:base + 8]
            if ([partition, subpartition, kernel, destination] != list(task[:4]) or row_offset != ordinal * vertices * 2 or
                    pma_offset != position or slots % 16 or not slots or control not in (0, 1) or position + slots > len(pma)):
                raise ValueError("adapter task geometry/order")
            expected = sorted(((compact[i] & 0x7fffffff) << 32) | (compact[i + 1] - destination)
                for i in range(task[5], task[5] + task[6], 2) if not compact[i + 1] & EMPTY)
            duplicates += len(expected) - len(set(expected))
            if bool(control) != (not expected): raise ValueError("adapter empty task control")
            empty += control; observed = []; previous = 0
            for source in range(vertices):
                end, begin = rows[row_offset + source * 2:row_offset + source * 2 + 2]
                if begin != previous or begin % 16 or end % 16 or not begin <= end <= slots: raise ValueError("adapter row bounds")
                previous = end; values = pma[position + begin:position + end]; live = []
                for word in values:
                    if word == EMPTY: continue
                    if word >= 65536: raise ValueError("adapter destination domain")
                    live.append(word); observed.append((source << 32) | word)
                if live != sorted(live) or list(values) != live + [EMPTY] * (len(values) - len(live)):
                    raise ValueError("adapter compact sorted source16 PMA")
                if values and len(values) != max(16, (len(live) + 15) // 16 * 16): raise ValueError("adapter minimum row reservation")
                if stream is not None:
                    payload = stream.read(len(values) * 8)
                    if len(payload) != len(values) * 8: raise ValueError("adapter packet capture extent")
                    for index, word in enumerate(values):
                        dummy = EMPTY if word == EMPTY else 0
                        expected_packet = (source | dummy, (destination + (word & 0x7ffff)) | dummy)
                        if struct.unpack_from("<2I", payload, index * 8) != expected_packet: raise ValueError("adapter packet value/order")
            if previous != slots or observed != expected: raise ValueError("adapter complete logical edge multiset")
            segments = slots // 16; even, odd = (segments + 1) // 2, segments // 2
            for route, value in enumerate((min(even, 131072), max(0, even - 131072), min(odd, 131072), max(0, odd - 131072))): reads[route] += value
            logical += len(expected); physical += slots; position += slots
        if position != len(pma) or logical != original[3] or stream is not None and stream.read(1): raise ValueError("adapter full graph/capture extent")
    finally:
        if stream is not None: stream.close()
    row_reads = (vertices + 1) * count
    return {"passed": True, "tasks": count, "vertices": vertices, "logical_edges": logical, "physical_edges": physical,
        "dummy_edges": physical - logical, "row_word_reads": row_reads, "pma_segment_reads": reads,
        "source_row_read_bytes": row_reads * 8, "source_pma_read_bytes": physical * 4}, {"empty_task_controls": empty, "duplicate_edge_entries": duplicates}


def analyze(directory: Path, output: Path, stdout: Path, stderr: Path):
    capture = output / "adapter_edges.u32le"; facts, controls = inspect(directory, capture)
    lines = stdout.read_text().splitlines()
    if len(lines) != 1 or not lines[0].startswith("ADAPTER_SOURCE ") or stderr.read_text(): raise ValueError("adapter unexpected diagnostics")
    observed = json.loads(lines[0][len("ADAPTER_SOURCE "):], object_pairs_hook=unique_fields)
    if json.dumps(observed, sort_keys=True) != json.dumps(facts, sort_keys=True): raise ValueError("adapter counters mismatch")
    return {"result": facts, **controls, "capture_sha256": sha256_file(capture), "capture_bytes": capture.stat().st_size,
        "device_cycles": None, "matched_A4_B_overhead": None, "publication_error_pct": None}
