"""Validate complete generation state, retained addresses and raw DMA/kernel intervals."""

import json

from ..continuous_board.analysis import TIMES, nonnegative
from ..continuous_board.execution.events import STAMP_KEYS, window
from ..native_board.analysis import check_events
from .preparation import CASE

PASS = "METADATA_G_HOST_PASS_NOT_BOARD"
BOARD_PASS = "METADATA_G_BOARD_PASS_NOT_BASELINE_ADMISSION"


def analyze(stdout, stderr, *, bdf=None):
    lines = stdout.splitlines()
    board = bdf is not None
    if stderr.strip() or not lines or not lines[0].startswith("METADATA_G_SETUP ") or \
            lines[-1] != (BOARD_PASS if board else PASS):
        raise ValueError("incomplete metadata lifecycle transcript")
    setup = json.loads(lines[0].removeprefix("METADATA_G_SETUP "))
    if set(setup) != {"board", "one_time_setup_ms", "shards", "hbm_bytes"} | ({"device_bdf"} if board else set()) or \
            setup["board"] is not board or not nonnegative(setup["one_time_setup_ms"]) or any(
                type(setup[key]) is not int or setup[key] != CASE[key] for key in ("shards", "hbm_bytes")) or \
            board and setup["device_bdf"] != bdf:
        raise ValueError("metadata lifecycle geometry/leased device changed")
    generations, rows, events, pending = [], [], [], []
    previous_end = -1
    for line in lines[1:-1]:
        prefix, payload = line.split(" ", 1)
        record = json.loads(payload)
        if prefix == "METADATA_G_EVENT":
            if not board or set(record) != {"generation", "batch", "shard", "role", *STAMP_KEYS} or any(
                    type(record[key]) is not int or record[key] < 0 for key in ("generation", "shard", *STAMP_KEYS)) or \
                    type(record["batch"]) is not int or record["batch"] < -1 or record["shard"] >= CASE["shards"]:
                raise ValueError("invalid metadata lifecycle event")
            stamps = [record[key] for key in STAMP_KEYS]
            if stamps != sorted(stamps) or stamps[3] <= stamps[2] or stamps[0] <= previous_end:
                raise ValueError("metadata lifecycle event order changed")
            pending.append(record)
            events.append(record)
        elif prefix == "METADATA_G_GENERATION":
            generation = len(generations)
            if len(rows) != 3 * generation or generation >= 2 or set(record) != {
                    "generation", "metadata_preparation_ms", "metadata_dma_ms", "same_bos", "restored_pma"} or \
                    type(record["generation"]) is not int or record["generation"] != generation or \
                    record["same_bos"] is not True or record["restored_pma"] is not False or any(
                        not nonnegative(record[key]) for key in ("metadata_preparation_ms", "metadata_dma_ms")):
                raise ValueError("metadata generation omitted/reordered or BO/PMA reset")
            if board and generation:
                expected = {(shard, role) for shard in range(CASE["shards"])
                            for role in ("metadata_row_dma", "metadata_binary_dma")}
                if len(pending) != len(expected) or {(e["shard"], e["role"]) for e in pending} != expected or \
                        any(e["generation"] != generation or e["batch"] != -1 for e in pending) or \
                        record["metadata_dma_ms"] <= 0 or \
                        window(pending)[1] > record["metadata_dma_ms"] + 0.01:
                    raise ValueError("metadata generation DMA incomplete or timing invalid")
                previous_end = max(e["end_ns"] for e in pending)
            elif pending:
                raise ValueError("unexpected metadata generation events")
            generations.append(record)
            pending = []
        elif prefix == "METADATA_G_ROW":
            generation, batch = divmod(len(rows), 3)
            expected = {**CASE["batches"][batch], "generation": generation, "checked_words": CASE["checked_words"]}
            flags = {"board": board, "complete_state_pass": True, "metadata_pass": True, "restored_pma": False}
            if len(generations) != generation + 1 or generation >= 2 or set(record) != set(expected) | set(flags) | set(TIMES) or any(
                    type(record[key]) is not int or record[key] != value for key, value in expected.items()) or any(
                    record[key] is not value for key, value in flags.items()) or any(not nonnegative(record[key]) for key in TIMES) or \
                    record["g_ready_wall_ms"] + 1e-6 < sum(record[key] for key in TIMES[:3]):
                raise ValueError("metadata lifecycle complete-state/timing row changed")
            if board:
                if any(e["generation"] != generation or e["batch"] != batch for e in pending):
                    raise ValueError("event assigned to wrong metadata transaction")
                check_events(CASE, record, pending)
                previous_end = max(e["end_ns"] for e in pending)
            elif pending or record["kernel_busy_ms"] or record["kernel_span_ms"]:
                raise ValueError("CPU lifecycle promoted to board evidence")
            rows.append(record)
            pending = []
        else:
            raise ValueError("unknown metadata lifecycle output")
    if len(generations) != 2 or len(rows) != 6 or pending:
        raise ValueError("metadata lifecycle matrix incomplete")
    return {"setup": setup, "generations": generations, "rows": rows, "events": events}


def stale_rejection(stdout, stderr):
    lines = stdout.splitlines()
    if stderr.strip() != "complete resident PMA/padding mismatch":
        raise ValueError("stale-directory negative failed for another reason")
    if not lines or not lines[0].startswith("METADATA_G_SETUP "):
        raise ValueError("stale-directory negative lacks setup")
    expected = [("METADATA_G_GENERATION", 0, None), *(('METADATA_G_ROW', 0, batch) for batch in range(3)),
                ("METADATA_G_GENERATION", 1, None), ("METADATA_G_ROW", 1, 0)]
    # Seven lines precede the rejected transaction; no passing final sentinel.
    if len(lines) != len(expected) + 1:
        raise ValueError("stale-directory negative failed at another transaction")
    for line, (kind, generation, batch) in zip(lines[1:], expected):
        prefix, payload = line.split(" ", 1)
        row = json.loads(payload)
        if prefix != kind or row.get("generation") != generation or batch is not None and row.get("batch") != batch:
            raise ValueError("stale-directory negative prefix changed")
    # Replay every successful prefix row with the normal strict validator.
    final = json.loads(lines[-1].split(" ", 1)[1])
    supplement = []
    for batch in (1, 2):
        supplement.append("METADATA_G_ROW " + json.dumps({**final, **CASE["batches"][batch]}))
    analyze("\n".join([*lines, *supplement, PASS]) + "\n", "")
    return {"expected_rejection": True, "generation": 1, "batch": 1, "cpu_only": True}
