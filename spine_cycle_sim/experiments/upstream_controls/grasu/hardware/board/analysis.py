"""Validate nine event records and a complete original-G state check."""

import json
import math
import statistics

from .. import configuration as config

BOUNDARY = "resident_argument_binding_enqueue_wait_excluding_preparation_preload_readback"
ROLES = {f"{kind}_{i}" for kind, count in config.KERNELS.items() for i in range(1, count + 1)}


def inspect(stdout, stderr, case, bdf):
    lines = stdout.read_text().splitlines()
    if stderr.read_bytes() or len(lines) != 10 or any(not line.startswith("ORIGINAL_G_EVENT ") for line in lines[:9]) or \
            not lines[-1].startswith("ORIGINAL_G_BOARD "):
        raise ValueError("original G board diagnostics or incomplete events")
    events = [json.loads(line.removeprefix("ORIGINAL_G_EVENT ")) for line in lines[:9]]
    observed = json.loads(lines[-1].removeprefix("ORIGINAL_G_BOARD "))
    if {row.get("role") for row in events} != ROLES:
        raise ValueError("original G event CU set differs")
    for row in events:
        times = [row.get(key) for key in ("queued", "submitted", "start", "end")]
        if any(type(value) is not int or value < 0 for value in times) or not times[0] <= times[1] <= times[2] < times[3]:
            raise ValueError("original G event timestamps invalid")
    span = max(row["end"] for row in events) - min(row["start"] for row in events)
    expected = {"status": "FULL_STATE_PASS", "bdf": bdf, "updates": case["facts"]["updates"],
        "checked_slots_including_guards": case["expected_slots_including_guards"],
        "kernel_event_span_ns": span, "readback_in_wall": False, "host_preparation_in_wall": False, "events": 9}
    wall = observed.get("resident_wall_ms")
    if {key: value for key, value in observed.items() if key != "resident_wall_ms"} != expected or \
            type(wall) not in (int, float) or not math.isfinite(wall) or wall <= 0 or span > wall * 1e6 + 1e4:
        raise ValueError("original G state/counters/BDF/timing differs")
    return {"events": events, "observation": observed, "boundary": BOUNDARY}


def summaries(rows, names, repeats):
    if {(row["case"], row["repeat"]) for row in rows} != {(name, rep) for name in names for rep in range(repeats)} or \
            len(rows) != len(names) * repeats:
        raise ValueError("complete original G repeated matrix required")
    return [{"case": name, "repeats": repeats, "boundary": BOUNDARY,
        "median_resident_wall_ms": statistics.median(row["analysis"]["observation"]["resident_wall_ms"]
            for row in rows if row["case"] == name),
        "median_kernel_event_span_ms": statistics.median(row["analysis"]["observation"]["kernel_event_span_ns"] / 1e6
            for row in rows if row["case"] == name)} for name in names]
