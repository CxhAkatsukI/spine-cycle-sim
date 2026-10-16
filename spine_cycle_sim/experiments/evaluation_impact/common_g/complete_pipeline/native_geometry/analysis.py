"""Validate all fixed native hot/cold source rows without promoting their scope."""

import json

from ..analysis import WARNING_PAIR

PASS = "NATIVE_G_SOURCE_PASS_NOT_RTL_OR_BOARD"
CLAIMS = ("hardware_timing_admitted", "production_baseline_admitted",
          "publication_match_admitted", "integrated_rtl_admitted")
CONTRACT = {"vertices": 262148, "partition_vertices": 65536, "shards": 5,
            "cache_segments_per_half": 131072, "reserved_operations": 1048592,
            "executed_operations": 40, "populated_shards": [0, 4], "empty_shards": [1, 2, 3],
            "source_ids": [0, 1, 2, 3, 262142, 262143, 262144, 262145, 262146, 262147],
            "ports_nonempty_batch": [6, 4, 6, 4], "packets_per_batch": 1048598,
            "edges_per_batch": [524296, 524276, 524296],
            "reservation_scope": "full synthetic future trace sets production permutation and fixed capacity",
            "execution_scope": "sparse empty/delete/insert schedule, not the complete reservation trace"}


def analyze(stdout, stderr):
    lines = stdout.splitlines()
    if len(lines) != 8 or not lines[0].startswith("NATIVE_G_SETUP ") or lines[-1] != PASS or any(
            not line.startswith("NATIVE_G_ROW ") for line in lines[1:-1]):
        raise ValueError("incomplete native source execution")
    setup = json.loads(lines[0].removeprefix("NATIVE_G_SETUP "))
    expected_setup = {key: CONTRACT[key] for key in
                      ("vertices", "shards", "partition_vertices", "cache_segments_per_half",
                       "reserved_operations", "executed_operations")}
    if (set(setup) != set(expected_setup) | {"board", "hbm_bytes"} or
            any(type(setup.get(key)) is not int or setup[key] != value for key, value in expected_setup.items()) or
            setup.get("board") is not False or type(setup.get("hbm_bytes")) is not int or
            not 0 < setup["hbm_bytes"] <= 23 * 512 * 1024**2):
        raise ValueError("native geometry, cache capacity or source-only boundary changed")
    rows = [json.loads(line.removeprefix("NATIVE_G_ROW ")) for line in lines[1:-1]]
    for row, (arm, batch) in zip(rows, ((a, b) for a in (0, 1) for b in range(3)), strict=True):
        counts = {"registered": arm, "batch": batch, "updates": 20 if batch else 0,
                  "edges": CONTRACT["edges_per_batch"][batch], "packets": CONTRACT["packets_per_batch"],
                  **dict(zip(("hot_even", "cold_even", "hot_odd", "cold_odd"),
                             CONTRACT["ports_nonempty_batch"] if batch else [0] * 4, strict=True))}
        flags = {"complete_state_pass": True, "direct_handoff_pass": True, "metadata_pass": True,
                 "restored_pma": False, "board": False}
        if (set(row) != set(counts) | set(flags) or
                any(type(row[key]) is not int or row[key] != value for key, value in counts.items()) or
                any(row[key] is not value for key, value in flags.items())):
            raise ValueError("native hot/cold state, metadata, order or handoff mismatch")
    # Original hot/cold inserts emit 20 pairs; registered cold DDR emits 8.
    remaining = stderr
    for warning in WARNING_PAIR:
        if remaining.count(warning) != 28:
            raise ValueError("native pristine/cold-DDR diagnostic count changed")
        remaining = remaining.replace(warning, "")
    if remaining.strip():
        raise ValueError("unclassified native source diagnostic")
    return {"setup": setup, "rows": rows}
