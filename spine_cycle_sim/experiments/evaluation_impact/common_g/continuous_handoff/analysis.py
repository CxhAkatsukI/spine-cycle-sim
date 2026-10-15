"""Reject incomplete convergence, changed policies and host timing promoted to FPGA."""

import json

from ..continuous_board.analysis import CLAIMS, nonnegative

PASS = "CONTINUOUS_GR_HOST_MODEL_PASS_NOT_BOARD"
UNIT_PASS = "CONTINUOUS_GR_RESIDENT_UNIT_PASS"
TIMES = ("host_preparation_ms", "g_ready_wall_ms", "host_inclusive_e2e_ms", "g_busy_ms",
         "r_busy_ms", "oracle_ms", "verification_ms")


def analyze(case, stdout, stderr):
    lines = stdout.splitlines()
    if stderr.strip() or len(lines) != 5 or lines[-1] != PASS or \
            not lines[0].startswith("CONTINUOUS_GR_SETUP "):
        raise ValueError("incomplete or non-host handoff output")
    setup = json.loads(lines[0].removeprefix("CONTINUOUS_GR_SETUP "))
    if setup.get("board") is not False or setup.get("initial_state") != "old_graph_converged" or \
            type(setup["source"]) is not int or setup["source"] != 0 or \
            type(setup["round_limit"]) is not int or setup["round_limit"] != 2048 or \
            type(setup["shards"]) is not int or setup["shards"] != case["shards"] or \
            setup["shards"] != 1 or not nonnegative(setup["one_time_setup_ms"]) or len(case["batches"]) != 3:
        raise ValueError("incorrect resident handoff setup")
    rows = []
    for line, expected in zip(lines[1:4], case["batches"], strict=True):
        if not line.startswith("CONTINUOUS_GR_ROW "):
            raise ValueError("unexpected handoff output")
        row = json.loads(line.removeprefix("CONTINUOUS_GR_ROW "))
        if any(type(row[key]) is not type(value) or row[key] != value for key, value in expected.items()) or \
                row.get("board") is not False or row.get("converged") is not True or \
                row.get("state_pass") is not True or row.get("restored_pma") is not False or \
                type(row["checked_words"]) is not int or row["checked_words"] != 2 * 131072 * 16 + 32 or \
                type(row["checked_vertices"]) is not int or row["checked_vertices"] != case["vertices"] or \
                any(not nonnegative(row[key]) for key in TIMES):
            raise ValueError("handoff state/policy scope disagreement")
        counts = row["active_counts"]
        if type(counts) is not list or not counts or len(counts) > setup["round_limit"] or \
                type(row["rounds"]) is not int or row["rounds"] != len(counts) or counts[-1] != 0 or \
                any(type(value) is not int or not 0 <= value <= case["vertices"] for value in counts) or \
                any(value == 0 for value in counts[:-1]) or \
                (row["batch"] == 0 and (counts != [0] or row["fallback"] or row["seed_sources"])):
            raise ValueError("invalid convergence trajectory")
        if any(row[key] != 0 for key in ("host_inclusive_e2e_ms", "g_busy_ms", "r_busy_ms")) or \
                row["g_ready_wall_ms"] + 1e-6 < row["host_preparation_ms"]:
            raise ValueError("host-only timing promoted to FPGA timing")
        rows.append(row)
    return {"setup": setup, "rows": rows}
