"""Replay raw event timestamps and full-state facts without fitting timings."""

import json
import math
import statistics

from ...continuous_board.execution.events import ROLES, STAMP_KEYS, window
from ..analysis import expected

BOUNDARY = "resident_argument_binding_enqueue_wait_including_publication_barrier"
TIMES = ("one_time_setup_ms", "pack_ms", "dma_wall_ms", "launch_wait_ms", "g_ready_wall_ms",
         "kernel_busy_ms", "kernel_span_ms", "oracle_ms", "verification_readback_ms")


def _close(actual, reference):
    # The frozen C++ host prints six significant digits, not raw doubles.
    return math.isclose(actual, reference, rel_tol=6e-6, abs_tol=1e-8)


def inspect(stdout, stderr, case):
    if stderr:
        raise ValueError("unclassified matched-G board diagnostic")
    lines = stdout.splitlines()
    count = len(ROLES) + min(4, case["facts"]["updates"])
    if len(lines) != count + 1 or any(not line.startswith("MATCHED_G_EVENT ") for line in lines[:-1]) or \
            not lines[-1].startswith("MATCHED_G_BOARD "):
        raise ValueError("incomplete matched-G events or board observation")
    events = [json.loads(line.removeprefix("MATCHED_G_EVENT ")) for line in lines[:-1]]
    row = json.loads(lines[-1].removeprefix("MATCHED_G_BOARD "))
    for event in events:
        if set(event) != {"role", "shard", *STAMP_KEYS} or event["role"] not in ROLES | {"update_dma"} or \
                any(type(event[key]) is not int or event[key] < 0 for key in ("shard", *STAMP_KEYS)) or \
                event["shard"] != 0:
            raise ValueError("matched-G event role, shard or typed timestamps differ")
        stamps = [event[key] for key in STAMP_KEYS]
        if stamps != sorted(stamps) or stamps[-1] <= stamps[-2]:
            raise ValueError("matched-G event timestamps invalid")
    kernels = [event for event in events if event["role"] != "update_dma"]
    transfers = [event for event in events if event["role"] == "update_dma"]
    if len(kernels) != len(ROLES) or {event["role"] for event in kernels} != ROLES:
        raise ValueError("missing or duplicate production G/barrier event")
    facts = {"status": "PASS", "updates": case["facts"]["updates"],
             "checked_words": expected(case)["checked_words"],
             "complete_state_pass": True, "metadata_pass": True}
    if set(row) != set(facts) | set(TIMES) or json.dumps(
            {key: row[key] for key in facts}, sort_keys=True) != json.dumps(facts, sort_keys=True) or any(
                type(row[key]) not in (int, float) or not math.isfinite(row[key]) or row[key] < 0 for key in TIMES):
        raise ValueError("matched-G complete-state, metadata or timing facts differ")
    busy, span = window(kernels)
    if not _close(row["kernel_busy_ms"], busy) or not _close(row["kernel_span_ms"], span) or \
            span > row["launch_wait_ms"] + 0.01 or row["g_ready_wall_ms"] + 0.001 < sum(
                row[key] for key in ("pack_ms", "dma_wall_ms", "launch_wait_ms")):
        raise ValueError("matched-G raw events disagree with reported timing window")
    if transfers and (max(event["end_ns"] for event in transfers) > min(event["queued_ns"] for event in kernels) or
                      window(transfers)[1] > row["dma_wall_ms"] + 0.01):
        raise ValueError("matched-G DMA overlaps or exceeds its declared wall window")
    producer_busy, producer_span = window([event for event in kernels if event["role"] != "barrier"])
    return {"observation": row, "events": events, "boundary": BOUNDARY,
            "producer_busy_ms": producer_busy, "producer_span_ms": producer_span}


def summaries(rows, names, repeats):
    if len(rows) != len(names) * repeats or {(row["case"], row["repeat"]) for row in rows} != {
            (name, repeat) for name in names for repeat in range(repeats)}:
        raise ValueError("complete repeated matched-G matrix required")
    return [{"case": name, "repeats": repeats, "boundary": BOUNDARY, **{
        "median_" + key: statistics.median(row["analysis"]["observation"][key] for row in rows if row["case"] == name)
        for key in TIMES}} for name in names]
