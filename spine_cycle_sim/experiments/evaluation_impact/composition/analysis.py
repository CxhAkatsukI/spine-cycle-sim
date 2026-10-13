"""Validate the complete declared physical-handoff correctness matrix."""

import json


FIXTURES = ((129, 1, False), (65569, 1, False), (131105, 8, False), (65569, 1, True))
REJECTIONS = {"row", "segment", "extent", "source0-reservation", "placement", "inflight", "missing-row"}
MEASUREMENTS = ("g_cycles", "r_cycles", "rounds", "r_read_bytes", "r_write_bytes")


def analyze(stdout):
    rows, rejections = [], []
    for line in stdout.splitlines():
        tag, _, body = line.partition(" ")
        if tag == "HANDOFF_RESULT":
            rows.append(json.loads(body))
        elif tag == "HANDOFF_REJECTION":
            rejections.append(json.loads(body))
    expected = {(v, cache, empty, reverse) for v, cache, empty in FIXTURES for reverse in (False, True)}
    observed = set()
    for row in rows:
        if type(row["empty"]) is not bool or type(row["reverse"]) is not bool:
            raise ValueError("handoff matrix flags must be boolean")
        key = (row["vertices"], row["cache_segments"], row["empty"], row["reverse"])
        if key in observed or key not in expected:
            raise ValueError("duplicate or undeclared handoff observation")
        observed.add(key)
        if row["physical_handoff_pass"] is not True or row["performance_admitted"] is not False:
            raise ValueError("handoff correctness must not imply performance admission")
        for field in MEASUREMENTS:
            if type(row[field]) is not int or row[field] < 0:
                raise ValueError("invalid handoff counter: " + field)
        if min(row["r_cycles"], row["rounds"], row["r_read_bytes"], row["r_write_bytes"]) == 0:
            raise ValueError("R must actually execute and publish")
        if not row["empty"] and row["g_cycles"] == 0:
            raise ValueError("nonempty G window omitted")
    if observed != expected or len(rows) != len(expected):
        raise ValueError("incomplete handoff matrix")
    names = [row["case"] for row in rejections]
    if len(names) != len(REJECTIONS) or set(names) != REJECTIONS or any(
            row["rejected"] is not True for row in rejections):
        raise ValueError("incomplete or duplicate rejection matrix")
    for v, cache, empty in FIXTURES:
        pair = [row for row in rows if (row["vertices"], row["cache_segments"], row["empty"]) == (v, cache, empty)]
        if any(pair[0][field] != pair[1][field] for field in MEASUREMENTS):
            raise ValueError("registration-order timing or traffic changed")
    return {
        "status": "RESIDENT_HANDOFF_CORRECTNESS_PASS_NOT_BASELINE_ADMISSION",
        "rows": rows, "rejections": rejections, "registration_order_exact": True,
        "physical_handoff_admitted": True, "whole_g_candidate_integrated": False,
        "host_window_measured": False, "baseline_admitted": False,
        "hardware_timing_admitted": False, "publication_match_admitted": False,
        "new_spine_comparison_executed": False,
    }
