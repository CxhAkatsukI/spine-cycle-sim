"""Conserved current-input diagnostics, never a complete-R admission gate."""

from .prefetch_analysis import parse

MATRIX = [(latency, reverse, mode, period) for latency in (64, 128)
          for reverse in (0, 1) for mode, period in
          (("single", 1), ("dual-port", 1), ("current-input", 1), ("current-input", 5))]


def summarize(rows, legacy, complete):
    identities = [(r["latency"], r["reverse"], r["mode"], r["sink_period"]) for r in rows]
    if len(rows) != len(MATRIX) or set(identities) != set(MATRIX):
        raise ValueError("complete declared input matrix required")
    indexed = dict(zip(identities, (r["observations"] for r in rows)))
    old = {(r["latency"], r["reverse"], "single" if r["ports"] == 1 else "dual-port", 1):
           r["observations"] for r in legacy}
    if len(old) != 8 or not old.keys() <= indexed.keys():
        raise ValueError("eight immutable historical reader controls required")
    if any(indexed[key] != value for key, value in old.items()):
        raise ValueError("historical input observation changed")
    for latency in (64, 128):
        for mode, period in (("single", 1), ("dual-port", 1), ("current-input", 1), ("current-input", 5)):
            if indexed[(latency, 0, mode, period)] != indexed[(latency, 1, mode, period)]:
                raise ValueError("registration order changed input observations")
    summaries = []
    for latency in (64, 128):
        fast, slow = (indexed[(latency, 0, "current-input", period)] for period in (1, 5))
        old_row = indexed[(latency, 0, "single", 1)]
        for row in (fast, slow):
            if row["schema_version"] != 6 or row["read_bytes"] != old_row["read_bytes"]:
                raise ValueError("current architecture or physical byte conservation failed")
            for worker, old_worker in zip(row["workers"], old_row["workers"]):
                if any(worker[key] != old_worker[key] for key in
                       ("worker", "physical_slots", "live_edges", "packets", "input_dummy", "output_dummy")):
                    raise ValueError("logical edge/packet/slot ledger changed")
        if slow["cycles"] < fast["cycles"] or not any(
                w["publisher_output_stalls"] > 0 for w in slow["workers"]):
            raise ValueError("throttled sink did not exercise backpressure")
        pair = [r["observations"] for r in complete if r["latency"] == latency and
                r["arm"] == "prefetch_sssp_write_issue"]
        controls = [r["observations"] for r in complete if r["latency"] == latency and r["arm"] == "a4_io16"]
        if len(pair) != 2 or pair[0] != pair[1] or len(controls) != 2 or controls[0] != controls[1]:
            raise ValueError("complete current R and A4 registration pairs required")
        candidate, a4 = pair[0]["result"], controls[0]["result"]
        if candidate["rounds"] != 46 or a4["rounds"] != 46:
            raise ValueError("same 46-round convergence reference required")
        summaries.append(dict(latency=latency, input_scan_cycles=fast["cycles"],
            throttled_scan_cycles=slow["cycles"], complete_R_cycles=candidate["cycles"],
            complete_A4_cycles=a4["cycles"], unchanged_46_input_scans_cycles=46 * fast["cycles"],
            input_scans_over_complete_R=46 * fast["cycles"] / candidate["cycles"],
            input_scans_over_complete_A4=46 * fast["cycles"] / a4["cycles"],
            input_sink_endpoints=[w["sink_done"] for w in fast["workers"]]))
    return dict(rows=summaries, historical_rows_exact=8, registration_pairs_exact=8,
        integrated_R_retention_passed=False, hardware_calibrated=False,
        claim="same_finite_reader_without_downstream_not_a_complete_R_speedup")
