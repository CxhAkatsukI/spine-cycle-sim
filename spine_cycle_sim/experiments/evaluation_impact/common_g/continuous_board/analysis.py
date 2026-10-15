"""Check the exact declared host matrix without promoting it to FPGA evidence."""

import json
import math

PASS = "CONTINUOUS_G_HOST_MODEL_PASS_NOT_BOARD"
BOARD_PASS = "CONTINUOUS_G_BOARD_CORRECTNESS_PASS_NOT_BASELINE_ADMISSION"
CLAIMS = ("hardware_timing_admitted", "production_baseline_admitted", "publication_match_admitted",
          "integrated_rtl_admitted", "complete_GR_admitted")
TIMES = ("host_preparation_ms", "transfer_wall_ms", "launch_wait_ms", "g_ready_wall_ms",
         "kernel_busy_ms", "kernel_span_ms", "oracle_ms", "verification_readback_ms")


def nonnegative(value):
    return type(value) in (int, float) and math.isfinite(value) and value >= 0


def analyze(case, stdout, stderr):
    if stderr.strip():
        raise ValueError("unexpected host diagnostic")
    lines = stdout.splitlines()
    if len(lines) != 5 or lines[-1] != PASS or not lines[0].startswith("CONTINUOUS_G_SETUP "):
        raise ValueError("incomplete host-only output")
    setup = json.loads(lines[0].removeprefix("CONTINUOUS_G_SETUP "))
    if len(case["batches"]) != 3 or setup.get("board") is not False or \
            type(setup["shards"]) is not int or setup["shards"] != case["shards"] or \
            type(setup["hbm_bytes"]) is not int or setup["hbm_bytes"] <= 0 or \
            not nonnegative(setup["one_time_setup_ms"]):
        raise ValueError("invalid one-time host setup")
    rows = []
    for line, expected in zip(lines[1:4], case["batches"], strict=True):
        if not line.startswith("CONTINUOUS_G_ROW "):
            raise ValueError("unexpected host output")
        row = json.loads(line.removeprefix("CONTINUOUS_G_ROW "))
        if row.get("board") is not False or any(type(row[key]) is not int or row[key] != value
                for key, value in expected.items()) or type(row["checked_words"]) is not int or \
                row["checked_words"] != case["shards"] * (2 * 131072 * 16 + 32) or \
                row.get("complete_state_pass") is not True or row.get("metadata_pass") is not True or \
                row.get("restored_pma") is not False or any(not nonnegative(row[key]) for key in TIMES):
            raise ValueError("host matrix state/scope disagreement")
        if row["kernel_busy_ms"] != 0 or row["kernel_span_ms"] != 0 or \
                row["g_ready_wall_ms"] + 1e-6 < sum(row[key] for key in TIMES[:3]):
            raise ValueError("host-only timing promoted to device timing")
        rows.append(row)
    return {"setup": setup, "rows": rows}
