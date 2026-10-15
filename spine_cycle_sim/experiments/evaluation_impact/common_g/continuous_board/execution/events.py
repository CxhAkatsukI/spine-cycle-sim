"""Recompute measured event unions; no fitting or promotion to baseline evidence."""

import json
import math

from ..analysis import BOARD_PASS, TIMES, nonnegative

ROLES = {"cache0", "cache1", "ddr0", "ddr1", "dispatch", "search0", "search1", "search2", "search3", "barrier"}
STAMP_KEYS = ("queued_ns", "submit_ns", "start_ns", "end_ns")


def window(events):
    intervals = sorted((row["start_ns"], row["end_ns"]) for row in events)
    if not intervals:
        return 0.0, 0.0
    end, busy = intervals[0][0], 0
    for first, last in intervals:
        busy += max(0, last - max(first, end))
        end = max(end, last)
    return busy / 1e6, (end - intervals[0][0]) / 1e6


def close(actual, expected):
    return math.isclose(actual, expected, rel_tol=1e-8, abs_tol=2e-9)


def analyze(case, stdout, stderr, *, bdf):
    if stderr.strip():
        raise ValueError("unclassified board diagnostic; retain raw output")
    lines = stdout.splitlines()
    if len(lines) < 5 or not lines[0].startswith("CONTINUOUS_G_SETUP ") or lines[-1] != BOARD_PASS:
        raise ValueError("incomplete continuous board output")
    setup = json.loads(lines[0].removeprefix("CONTINUOUS_G_SETUP "))
    # This first board matrix covers single-shard, hot-only native inputs.
    if case["shards"] != 1 or case["partition_vertices"] != 65536 or len(case["batches"]) != 3:
        raise ValueError("board analyzer does not admit multi-shard or non-native inputs")
    if setup.get("board") is not True or type(setup.get("shards")) is not int or setup["shards"] != 1 or \
            setup.get("device_bdf") != bdf or type(setup.get("hbm_bytes")) is not int or \
            setup["hbm_bytes"] <= 0 or not nonnegative(setup.get("one_time_setup_ms")):
        raise ValueError("invalid board setup or leased device identity")
    rows, pending, previous_end = [], [], -1
    for line in lines[1:-1]:
        if line.startswith("CONTINUOUS_G_EVENT "):
            event = json.loads(line.removeprefix("CONTINUOUS_G_EVENT "))
            if set(event) != {"batch", "shard", "role", *STAMP_KEYS} or any(
                    type(event[key]) is not int or event[key] < 0 for key in ("batch", "shard", *STAMP_KEYS)) or \
                    event["batch"] != len(rows) or event["shard"] != 0 or \
                    event["role"] not in ROLES | {"update_dma"}:
                raise ValueError("event outside the declared batch, shard or role")
            stamps = [event[key] for key in STAMP_KEYS]
            if stamps != sorted(stamps) or event["end_ns"] <= event["start_ns"] or stamps[0] <= previous_end:
                raise ValueError("invalid event timestamps or cross-batch overlap")
            pending.append(event)
            continue
        if not line.startswith("CONTINUOUS_G_ROW ") or len(rows) >= 3:
            raise ValueError("unexpected board output")
        row = json.loads(line.removeprefix("CONTINUOUS_G_ROW "))
        expected = case["batches"][len(rows)]
        if row.get("board") is not True or any(type(row.get(key)) is not int or row[key] != value
                for key, value in expected.items()) or type(row.get("checked_words")) is not int or \
                row["checked_words"] != 2 * 131072 * 16 + 32 or row.get("complete_state_pass") is not True or \
                row.get("metadata_pass") is not True or row.get("restored_pma") is not False or \
                any(not nonnegative(row.get(key)) for key in TIMES):
            raise ValueError("board state, timing or padding disagreement")
        kernels = [event for event in pending if event["role"] != "update_dma"]
        transfers = [event for event in pending if event["role"] == "update_dma"]
        if len(kernels) != len(ROLES) or {event["role"] for event in kernels} != ROLES or \
                len(transfers) != min(4, expected["updates"]):
            raise ValueError("missing or duplicate G/barrier/DMA events")
        busy, span = window(kernels)
        if not close(row["kernel_busy_ms"], busy) or not close(row["kernel_span_ms"], span):
            raise ValueError("reported kernel union/span differs from raw events")
        if row["g_ready_wall_ms"] + 1e-6 < sum(row[key] for key in TIMES[:3]) or \
                span > row["launch_wait_ms"] + 0.01:
            raise ValueError("device events exceed the declared host timing window")
        if transfers and (max(event["end_ns"] for event in transfers) > min(event["queued_ns"] for event in kernels)
                          or window(transfers)[1] > row["transfer_wall_ms"] + 0.01):
            raise ValueError("DMA is outside its wall window or overlaps the post-DMA launch")
        rows.append(row)
        previous_end = max(event["end_ns"] for event in pending)
        pending = []
    if len(rows) != 3 or pending:
        raise ValueError("incomplete three-batch board matrix")
    return {"setup": setup, "rows": rows,
            "events": [json.loads(line.removeprefix("CONTINUOUS_G_EVENT ")) for line in lines
                       if line.startswith("CONTINUOUS_G_EVENT ")]}
