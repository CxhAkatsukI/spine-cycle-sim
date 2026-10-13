"""Admit complete cached sharded correctness, never infer performance matching."""

import json

from .analysis import MEASUREMENTS

STATUS = "CACHED_SHARDED_HANDOFF_CORRECTNESS_PASS_NOT_BASELINE_ADMISSION"
FIXTURES = ((65569, False, False), (65569, True, False), (131105, True, False), (65569, True, True))
COUNTERS = MEASUREMENTS + ("cache_updates", "ddr_updates", "pma_read_bytes", "pma_write_bytes")


def analyze(stdout):
    rows = {}
    expected = {(v, cold, empty, cached, reverse) for v, cold, empty in FIXTURES
                for cached, reverse in ((False, False), (True, False), (True, True))}
    for line in stdout.splitlines():
        tag, _, body = line.partition(" ")
        if tag != "CACHED_HANDOFF_RESULT":
            continue
        row = json.loads(body)
        if any(type(row[name]) is not bool for name in ("cold_high_source", "empty", "cached", "reverse")):
            raise ValueError("cached handoff flags must be boolean")
        key = tuple(row[name] for name in ("vertices", "cold_high_source", "empty", "cached", "reverse"))
        if key in rows or key not in expected or row["high_source"] != (row["vertices"] - 1) // 65536 * 65536:
            raise ValueError("duplicate or undeclared cached handoff identity")
        if row["physical_handoff_pass"] is not True or row["performance_admitted"] is not False:
            raise ValueError("cached correctness cannot admit performance")
        if any(type(row[name]) is not int or row[name] < 0 for name in COUNTERS) or \
                min(row[name] for name in MEASUREMENTS if name != "g_cycles") <= 0 or \
                (row["g_cycles"] == 0) != row["empty"]:
            raise ValueError("cached handoff omitted work")
        updates = 0 if row["empty"] else 8
        ddr = 4 if row["cold_high_source"] and updates else 0
        preload = 33554432 if row["cached"] and updates else 0
        pma_bytes = preload + (ddr if row["cached"] else updates) * 64
        if row["cache_updates"] != updates - ddr or row["ddr_updates"] != ddr or \
                row["pma_read_bytes"] != pma_bytes or row["pma_write_bytes"] != pma_bytes:
            raise ValueError("cached preload/writeback or update ledger changed")
        rows[key] = row
    if set(rows) != expected:
        raise ValueError("incomplete cached handoff matrix")
    for key, row in rows.items():
        direct = rows[key[:3] + (False, False)]
        if any(row[name] != direct[name] for name in MEASUREMENTS if name != "g_cycles"):
            raise ValueError("cached G changed R convergence, traffic or timing")
        if row["cached"]:
            other = rows[key[:4] + (not key[4],)]
            if any(row[name] != other[name] for name in COUNTERS):
                raise ValueError("R registration order changed cached observations")
    return {"status": STATUS, "rows": list(rows.values()), "full_cached_sharded_correctness": True,
            "complete_pma_oracle_pass": True, "r_time_work_traffic_exact": True,
            "r_registration_order_exact": True, "baseline_admitted": False,
            "hardware_timing_admitted": False, "publication_match_admitted": False,
            "host_window_measured": False, "new_spine_comparison_executed": False}
