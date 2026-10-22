"""Full-burst refill changes request grouping, not physical traffic or R admission."""

import json

from . import prefetch_analysis, reader_ports_analysis

MATRIX = [(latency, reverse, ports, full) for latency, reverse, ports in reader_ports_analysis.MATRIX
          for full in (False, True)]


def summarize(rows, before, a4):
    if [(r["latency"], r["reverse"], r["ports"], r["full_burst"]) for r in rows] != MATRIX:
        raise ValueError("complete sixteen-row refill matrix required")
    old = {(r["latency"], r["reverse"], r["ports"]): r["observations"] for r in before}
    if len(before) != 8 or set(old) != set(reader_ports_analysis.MATRIX):
        raise ValueError("complete eight-row pre-edit reader reference required")
    for row in rows:
        obs = row["observations"]
        prefetch_analysis.parse("PREFETCH_COMPACT " + json.dumps(obs))
        prior = old[row["latency"], row["reverse"], row["ports"]]
        if not row["full_burst"]:
            if obs != prior:
                raise ValueError("eager reader changed from pre-edit cycles or counters")
            continue
        if (obs.get("schema_version") != 4 or obs["masters_per_frontend"] != row["ports"]):
            raise ValueError("explicit full-burst topology required")
        for field in ("read_bytes", "live_edges", "packets"):
            if obs[field] != prior[field]:
                raise ValueError("refill silently changed physical input/output")
        for current, previous in zip(obs["workers"], prior["workers"]):
            for field in ("worker", "read_bytes", "read_beats", "physical_slots", "live_edges",
                          "packets", "input_dummy", "output_dummy"):
                if current[field] != previous[field]:
                    raise ValueError("per-shard physical input/output changed")
    summary = []
    for ports in (1, 2):
        candidate = [r for r in rows if r["ports"] == ports and r["full_burst"]]
        result = prefetch_analysis.summarize(candidate, a4)
        for row in result["rows"]:
            previous = old[row["latency"], 0, ports]
            observed = next(r["observations"] for r in candidate
                            if r["latency"] == row["latency"] and r["reverse"] == 0)
            row.update(ports=ports, physical_masters=ports * 4,
                prior_reader_cycles=previous["cycles"],
                prior_requests=previous["requests"], requests=observed["requests"],
                pma_requests=sum(w["pma_requests"] for w in observed["workers"]),
                short_pma_requests=sum(w["short_pma_requests"] for w in observed["workers"]),
                cycle_reduction=1 - observed["cycles"] / previous["cycles"],
                floor_already_exceeds_ten_percent=row["reader_floor_over_a4"] > 1.1)
            summary.append(row)
    return dict(rows=summary, pre_edit_rows_exact=8, input_layout_changed=False,
        integrated_r_retention_passed=False, claim="full_burst_reader_only_not_integrated_R")
