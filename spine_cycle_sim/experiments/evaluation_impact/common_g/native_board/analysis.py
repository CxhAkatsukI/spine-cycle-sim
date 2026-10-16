"""Strict native geometry/state checks and raw multi-shard event validation."""

import json

from ..continuous_board.analysis import CLAIMS, TIMES, nonnegative
from ..continuous_board.execution.events import ROLES, STAMP_KEYS, close, window
from .preparation import CASE

PASS = "NATIVE_G_HOST_MODEL_PASS_NOT_BOARD"
BOARD_PASS = "NATIVE_G_BOARD_CORRECTNESS_PASS_NOT_BASELINE_ADMISSION"


def analyze(case, stdout, stderr, *, bdf=None):
    if case != CASE or stderr.strip():
        raise ValueError("native case changed or unclassified diagnostic")
    board = bdf is not None
    lines = stdout.splitlines()
    if len(lines) < 5 or not lines[0].startswith("CONTINUOUS_G_SETUP ") or \
            lines[-1] != (BOARD_PASS if board else PASS):
        raise ValueError("incomplete native host/board transcript")
    setup = json.loads(lines[0].removeprefix("CONTINUOUS_G_SETUP "))
    if set(setup) != {"board", "shards", "hbm_bytes", "one_time_setup_ms"} | ({"device_bdf"} if board else set()) or \
            setup["board"] is not board or any(type(setup[key]) is not int or setup[key] != case[key]
                for key in ("shards", "hbm_bytes")) or not nonnegative(setup["one_time_setup_ms"]) or \
            board and setup["device_bdf"] != bdf:
        raise ValueError("native setup geometry or leased identity changed")
    rows, events, pending, previous_end = [], [], [], -1
    for line in lines[1:-1]:
        if line.startswith("CONTINUOUS_G_EVENT "):
            event = json.loads(line.removeprefix("CONTINUOUS_G_EVENT "))
            if not board or set(event) != {"batch", "shard", "role", *STAMP_KEYS} or any(
                    type(event[key]) is not int or event[key] < 0 for key in ("batch", "shard", *STAMP_KEYS)) or \
                    event["batch"] != len(rows) or event["shard"] >= case["shards"] or \
                    event["role"] not in ROLES | {"update_dma"}:
                raise ValueError("native event outside declared board, batch, shard or role")
            stamps = [event[key] for key in STAMP_KEYS]
            if stamps != sorted(stamps) or stamps[3] <= stamps[2] or stamps[0] <= previous_end:
                raise ValueError("native event stamps invalid or batches overlap")
            pending.append(event)
            events.append(event)
            continue
        if not line.startswith("CONTINUOUS_G_ROW ") or len(rows) >= 3:
            raise ValueError("unexpected native output")
        row = json.loads(line.removeprefix("CONTINUOUS_G_ROW "))
        expected = {**case["batches"][len(rows)], "checked_words": case["checked_words"]}
        flags = {"board": board, "complete_state_pass": True, "metadata_pass": True, "restored_pma": False}
        if set(row) != set(expected) | set(flags) | set(TIMES) or any(
                type(row[key]) is not int or row[key] != value for key, value in expected.items()) or any(
                row[key] is not value for key, value in flags.items()) or any(not nonnegative(row[key]) for key in TIMES):
            raise ValueError("native state, padding, metadata or timing disagreement")
        if row["g_ready_wall_ms"] + 1e-6 < sum(row[key] for key in TIMES[:3]):
            raise ValueError("native host timing window omits preparation, DMA or launch/wait")
        if board:
            check_events(case, row, pending)
            previous_end = max(event["end_ns"] for event in pending)
        elif pending or row["kernel_busy_ms"] or row["kernel_span_ms"]:
            raise ValueError("native host-only run promoted to hardware timing")
        rows.append(row)
        pending = []
    if len(rows) != 3 or pending:
        raise ValueError("native three-batch matrix incomplete")
    return {"setup": setup, "rows": rows, "events": events}


def check_events(case, row, events):
    kernels = [event for event in events if event["role"] != "update_dma"]
    transfers = [event for event in events if event["role"] == "update_dma"]
    previous_end = -1
    for shard in range(case["shards"]):
        group = [event for event in kernels if event["shard"] == shard]
        dma = [event for event in transfers if event["shard"] == shard]
        expected_dma = case["dma_lanes_per_populated_shard"] if row["updates"] and shard in case["populated_shards"] else 0
        if len(group) != len(ROLES) or {event["role"] for event in group} != ROLES or len(dma) != expected_dma:
            raise ValueError("missing or duplicate native shard kernel/barrier/DMA events")
        if min(event["queued_ns"] for event in group) <= previous_end:
            raise ValueError("native shard metadata was reused before prior shard completion")
        previous_end = max(event["end_ns"] for event in group)
    if [event["shard"] for event in kernels] != sorted(event["shard"] for event in kernels):
        raise ValueError("native shard launch order changed")
    busy, span = window(kernels)
    if not close(row["kernel_busy_ms"], busy) or not close(row["kernel_span_ms"], span) or \
            span > row["launch_wait_ms"] + 0.01:
        raise ValueError("native kernel timing differs from raw event union/span")
    if transfers and (max(event["end_ns"] for event in transfers) > min(event["queued_ns"] for event in kernels) or
                      window(transfers)[1] > row["transfer_wall_ms"] + 0.01):
        raise ValueError("native update DMA overlaps launch or exceeds its wall window")


def deterministic(result):
    return {"setup": {key: value for key, value in result["setup"].items() if key != "one_time_setup_ms"},
            "rows": [{key: value for key, value in row.items() if key not in TIMES} for row in result["rows"]]}
