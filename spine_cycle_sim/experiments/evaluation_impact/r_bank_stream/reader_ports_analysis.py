"""Explicit extra-master diagnostic; unchanged physical reads, no R admission."""

import json

from . import prefetch_analysis

MATRIX = [(latency, reverse, ports) for latency in (64, 128)
          for reverse in (0, 1) for ports in (1, 2)]


def summarize(rows, before, a4):
    if [(r["latency"], r["reverse"], r["ports"]) for r in rows] != MATRIX:
        raise ValueError("complete eight-row physical-reader matrix required")
    old = {(r["latency"], r["reverse"]): r["observations"] for r in before}
    if len(before) != 4 or set(old) != {(lat, rev) for lat in (64, 128) for rev in (0, 1)}:
        raise ValueError("complete four-row pre-edit reader reference required")
    for row in rows:
        obs = row["observations"]
        prefetch_analysis.parse("PREFETCH_COMPACT " + json.dumps(obs))
        if row["ports"] == 1 and obs != old[(row["latency"], row["reverse"])]:
            raise ValueError("one-port reader changed from pre-edit cycles or counters")
        if row["ports"] == 2:
            if obs.get("schema_version") != 3:
                raise ValueError("explicit two-port resource record required")
            previous = old[(row["latency"], row["reverse"])]
            for field in ("read_bytes", "live_edges", "packets"):
                if obs[field] != previous[field]:
                    raise ValueError("extra ports silently changed physical input or output")
            for current, prior in zip(obs["workers"], previous["workers"]):
                for field in ("worker", "read_bytes", "physical_slots", "live_edges", "packets",
                              "input_dummy", "output_dummy"):
                    if current[field] != prior[field]:
                        raise ValueError("per-shard physical input/output ledger changed")
    candidate = [dict(latency=r["latency"], reverse=r["reverse"], observations=r["observations"])
                 for r in rows if r["ports"] == 2]
    result = prefetch_analysis.summarize(candidate, a4)
    for row in result["rows"]:
        previous = old[(row["latency"], 0)]
        row["prior_reader_cycles"] = previous["cycles"]
        row["cycle_reduction"] = 1 - row["reader_only_scan_cycles"] / previous["cycles"]
        row["floor_already_exceeds_ten_percent"] = row["reader_floor_over_a4"] > 1.1
    return {**result, "pre_edit_rows_exact": 4, "physical_masters": 8,
            "input_layout_changed": False, "integrated_r_retention_passed": False,
            "claim": "extra_physical_reader_ports_diagnostic_not_complete_R"}
