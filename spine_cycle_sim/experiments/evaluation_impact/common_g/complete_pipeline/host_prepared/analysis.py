"""Require every declared resident batch, complete state and direct edge handoff."""

import json
from ..analysis import WARNING_PAIR

PASS = "REAL_HOST_PREPARED_G_SOURCE_PASS_NOT_RTL_OR_BOARD"
MARKER = "HOST_G_SOURCE_PASS internal_cache_ddr_fifos=unbounded timing_admitted=false"
CLAIMS = ("hardware_timing_admitted", "production_baseline_admitted",
          "publication_match_admitted", "integrated_rtl_admitted")


def analyze(case, stdout, stderr):
    lines = stdout.splitlines()
    if len(lines) != 7 or lines[-1] != MARKER or any(not line.startswith("HOST_G_ROW ") for line in lines[:-1]):
        raise ValueError("incomplete host-prepared source execution")
    rows = [json.loads(line.removeprefix("HOST_G_ROW ")) for line in lines[:-1]]
    if [(r["registered"], r["batch"]) for r in rows] != [(arm, b) for arm in (0, 1) for b in range(3)]:
        raise ValueError("missing/reordered host-prepared arm/batch")
    for r in rows:
        facts = case["batches"][r["batch"]]
        if (any(r[key] != case[key] for key in ("case", "vertices", "shards")) or
                any(r[key] != facts[key] for key in ("updates", "edges")) or
                r["complete_state_pass"] is not True or r["direct_handoff_pass"] is not True or
                not isinstance(r["packets"], int) or r["packets"] <= 0):
            raise ValueError("host input/state/handoff mismatch")
        ports = [r[key] for key in ("hot_even", "cold_even", "hot_odd", "cold_odd")]
        if any(type(n) is not int or n < 0 for n in ports) or sum(ports) != r["updates"] or ports[1] or ports[3]:
            raise ValueError("physical update/cache-port conservation")
    for batch in range(3):
        left, right = rows[batch].copy(), rows[batch + 3].copy()
        left.pop("registered"); right.pop("registered")
        if left != right:
            raise ValueError("original/candidate complete-state control differs")
    remaining = stderr
    for warning in WARNING_PAIR:
        # All edited segments are hot. Only the pristine cache arm uses the
        # vendor's mixed-width insertion operator; the registered arm does not.
        if remaining.count(warning) != case["positive_updates"]:
            raise ValueError("vendor diagnostic count differs from pristine positive updates")
        remaining = remaining.replace(warning, "")
    if remaining.strip():
        raise ValueError("unknown host-prepared execution diagnostic")
    return rows
