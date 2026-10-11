"""Input invariants and descriptive empty-row slopes, without timing fitting."""

import hashlib
import json
from pathlib import Path
from statistics import median
import struct

from .analysis import analyze_log
from .sst_input_audit import audit_resident_input


def inspect_fixture(graph: Path, fixture: Path) -> dict:
    audit = audit_resident_input(graph, fixture, 0)
    with fixture.open("rb") as stream:
        def words(count):
            return struct.unpack(f"<{count}I", stream.read(count * 4))
        magic, version, vertices, partitions, cache, rounds, active_count = words(7)
        if partitions != 1 or rounds != 2 or active_count != 1:
            raise ValueError("empty-row control requires one partition and two resident rounds")
        mapping, old = words(vertices), words(vertices)
        active, expected = words(active_count), words(vertices)
        updates, slots = words(2)
        bounds, pma = words(vertices * 2), words(slots)
        if stream.read(1):
            raise ValueError("trailing fixture data")
    if (mapping != tuple(range(vertices)) or active != (0,)
            or old[:5] != (0, 8, 16, 24, 32) or expected[:5] != (0, 8, 16, 24, 1)
            or any(value != 0xffffffff for value in old[5:] + expected[5:])
            or updates != 1 or any(bounds[2*v] != bounds[2*v+1] for v in range(4, vertices))):
        raise ValueError("added vertices changed the live prefix or resident state")
    tail = audit["tails"][0]
    if tail["last_occupied_source"] != 3 or tail["prefetched_row_count"] != 8:
        raise ValueError("live-row prefix changed")
    fixed = dict(cache=cache, rounds=rounds, active=active, updates=updates,
                 live_mapping=mapping[:5], old=old[:5], expected=expected[:5],
                 prefix_bounds=bounds[:8], slots=slots, pma=pma)
    return {"vertices": vertices, "trailing_empty_rows": tail["trailing_empty_rows"],
            "fixed_payload_sha256": hashlib.sha256(json.dumps(fixed, sort_keys=True).encode()).hexdigest(),
            "slots": slots, "audit": audit}


def adapter_samples(board: dict) -> dict:
    geometry = board["result"]
    if int(geometry["destination_partitions"]) != 1 or int(geometry["executed_supersteps"]) != 2:
        raise ValueError("board control geometry differs")
    events = {(e["stage"], e["round"]): e for e in board["events"]}
    duration, tail = [], []
    for index in range(2):
        a, g = (events[stage, index] for stage in ("adapter", "gather"))
        duration.append(a["end_ns"] - a["start_ns"])
        tail.append(max(0, a["end_ns"] - g["end_ns"]))
    return {"duration_ns": duration, "tail_ns": tail}


def summarize_case(directory: Path, vertices: int) -> dict:
    pair = json.loads((directory / "board/summary.json").read_text())
    if pair["status"] != "PAIRED_BOARD_PASS":
        raise ValueError("all paired board repetitions must pass")
    result = {"vertices": vertices, "arms": {}}
    for arm in ("original", "candidate"):
        samples = []
        for repeat in range(3):
            board = analyze_log((directory / f"board/r{repeat}_{arm}/run.log").read_text(), require_trace=True)
            if int(board["result"]["vertices"]) != vertices:
                raise ValueError("board vertex count changed")
            samples.append(adapter_samples(board))
        model = json.loads((directory / f"{arm}/result.json").read_text())
        summary = json.loads((directory / f"{arm}/summary.json").read_text())
        if (summary["status"] != "FUNCTIONAL_PASS_TIMING_DIAGNOSTIC"
                or not summary["complete_external_result_bytes_equal"]):
            raise ValueError("complete model correctness is required")
        model_events = {(e["stage"], e["round"]): e for e in model["invocations"]}
        durations, tails = [], []
        for index in (1, 2):
            a, g = (model_events[stage, index] for stage in ("adapter", "gather"))
            durations.append((a["end"] - a["start"]) * 1000 / 150)
            tails.append(max(0, a["end"] - g["end"]) * 1000 / 150)
        result["arms"][arm] = {
            "board_samples": samples,
            "board_median_duration_ns": median(x for s in samples for x in s["duration_ns"]),
            "board_median_tail_ns": median(x for s in samples for x in s["tail_ns"]),
            "model_median_duration_ns": median(durations), "model_median_tail_ns": median(tails),
            "model_round_duration_ns": durations, "model_round_tail_ns": tails,
            "nominal_compute_diagnostic": summary["timing"]}
    return result


def incremental_slopes(rows: list[dict]) -> list[dict]:
    if len(rows) < 2 or any(b["vertices"] <= a["vertices"] for a, b in zip(rows, rows[1:])):
        raise ValueError("strictly increasing vertex counts required")
    result = []
    for before, after in zip(rows, rows[1:]):
        delta = after["vertices"] - before["vertices"]
        entry = {"from_vertices": before["vertices"], "to_vertices": after["vertices"], "arms": {}}
        for arm in ("original", "candidate"):
            entry["arms"][arm] = {
                f"{source}_{metric}_ns_per_added_row":
                (after["arms"][arm][f"{source}_median_{metric}_ns"] -
                 before["arms"][arm][f"{source}_median_{metric}_ns"]) / delta
                for source in ("board", "model") for metric in ("duration", "tail")}
        result.append(entry)
    return result
