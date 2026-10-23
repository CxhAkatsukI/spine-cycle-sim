"""Finite reader/compactor admission, not an integrated-R retention decision."""

import json
import math


def transport_probes(stdout):
    rows = [json.loads(line.removeprefix("TRANSPORT_PROBE ")) for line in stdout.splitlines()
            if line.startswith("TRANSPORT_PROBE ")]
    if len(rows) != 2 or any(type(r.get("registered")) is not bool for r in rows) or {
            r["registered"] for r in rows} != {False, True}:
        raise ValueError("both single-initiator transport controls required")
    for row in rows:
        keys = ("beats", "cycles", "first_issue", "last_issue", "one_cycle_gaps", "two_cycle_gaps",
                "backend_submit_stalls")
        if any(type(row.get(k)) is not int or row[k] < 0 for k in keys):
            raise ValueError("integer transport probe counters required")
        interval = 2 if row["registered"] else 1
        if not (row["beats"] == 512 and 0 < row["first_issue"] < row["last_issue"] < row["cycles"] and
                row["last_issue"] - row["first_issue"] == 511 * interval and
                row["one_cycle_gaps"] == (0 if row["registered"] else 511) and
                row["two_cycle_gaps"] == (511 if row["registered"] else 0) and
                row["backend_submit_stalls"] == (512 if row["registered"] else 0)):
            raise ValueError("transport probe issue/arbiter gate failed")
    return rows


def parse(stdout):
    lines = [line.removeprefix("PREFETCH_COMPACT ") for line in stdout.splitlines()
             if line.startswith("PREFETCH_COMPACT ")]
    if len(lines) != 1:
        raise ValueError("exactly one candidate observation required")
    row = json.loads(lines[0])
    version = row.get("schema_version", 1)
    if type(version) is not int or version not in (1, 2, 3, 4, 5, 6):
        raise ValueError("unsupported candidate observation schema")
    if version == 6 and (row.get("refill_policy") != "full-burst" or any(
            type(row.get(key)) is not int or row[key] != expected for key, expected in
            (("physical_masters", 12), ("masters_per_frontend", 3), ("directory_tiles", 2),
             ("bank_lines", 512), ("pipeline_capacity", 3), ("pipeline_latency", 2)))):
        raise ValueError("current input requires explicit triple masters and finite 2-tile/512-line storage")
    if version == 5 and (row.get("refill_policy") != "available-space" or
            type(row.get("pipeline_capacity")) is not int or row["pipeline_capacity"] != 3 or
            type(row.get("pipeline_latency")) is not int or row["pipeline_latency"] != 2 or
            type(row.get("masters_per_frontend")) is not int or row["masters_per_frontend"] not in (1, 2) or
            type(row.get("physical_masters")) is not int or
            row["physical_masters"] != 4 * row["masters_per_frontend"]):
        raise ValueError("elastic reader requires explicit finite storage, unchanged latency and physical masters")
    if version == 4 and (row.get("refill_policy") != "full-burst" or
            type(row.get("masters_per_frontend")) is not int or
            row["masters_per_frontend"] not in (1, 2) or
            type(row.get("physical_masters")) is not int or
            row["physical_masters"] != 4 * row["masters_per_frontend"]):
        raise ValueError("full-burst reader requires explicit policy and physical masters")
    dual = version == 3 or (version in (4, 5) and row["masters_per_frontend"] == 2)
    if dual and any(type(row.get(k)) is not int or row[k] != expected for k, expected in
                    (("physical_masters", 8), ("masters_per_frontend", 2))):
        raise ValueError("dual-port reader requires eight explicit physical masters")
    if any(type(row.get(key)) is not int or row[key] <= 0 for key in
           ("cycles", "read_bytes", "requests", "live_edges", "packets")):
        raise ValueError("positive integer candidate totals required")
    if row.get("passed") is not True or row.get("live_edges") != 1450899:
        raise ValueError("candidate correctness/matrix gate failed")
    if len(row["workers"]) != 4 or {w["worker"] for w in row["workers"]} != set(range(4)):
        raise ValueError("four unique candidate workers required")
    for key in ("read_bytes", "requests", "live_edges", "packets"):
        if row[key] != sum(w[key] for w in row["workers"]):
            raise ValueError("candidate worker ledger does not close")
    if not all(type(w.get(key)) is int and w[key] >= 0 for w in row["workers"] for key in
               ("worker", "sink_done", "read_bytes", "requests", "physical_slots", "live_edges",
                "packets", "input_dummy", "output_dummy", "max_parents", "max_bank_lines", "max_lanes",
                "reader_output_stalls", "publisher_output_stalls")):
        raise ValueError("nonnegative integer candidate worker counters required")
    if not all(0 < w["sink_done"] <= row["cycles"] for w in row["workers"]):
        raise ValueError("candidate completion exceeds closed window")
    for w in row["workers"]:
        if version in (4, 6) and (any(type(w.get(k)) is not int for k in
                ("pma_requests", "short_pma_requests")) or
                not 0 < w["pma_requests"] <= w["requests"] or
                not 0 <= w["short_pma_requests"] <= min(4, w["pma_requests"])):
            raise ValueError("full-burst PMA parent/physical-tail ledger failed")
        if dual or version == 6:
            parents = w.get("parents_per_port", [])
            if (not isinstance(parents, list) or len(parents) != (3 if version == 6 else 2) or
                    any(type(p) is not int or not 0 < p <= 16 for p in parents) or
                    w["max_parents"] > sum(parents)):
                raise ValueError("dual-port physical parent bounds do not close")
        if not (1 < w["max_parents"] <= (48 if version == 6 else 32 if dual else 16) and
                0 < w["max_bank_lines"] <= (512 if version == 6 else 256) and
                0 < w["max_lanes"] <= 32 and w["live_edges"] + w["input_dummy"] == w["physical_slots"] and
                w["packets"] * 8 == w["live_edges"] + w["output_dummy"]):
            raise ValueError("candidate finite storage/physical lane gate failed")
    if version >= 2:
        keys = ("read_beats", "backend_submit_stalls", "selector_wait", "reader_pipeline_peak",
                "publisher_pipeline_peak")
        if any(type(w.get(k)) is not int or w[k] < 0 for w in row["workers"] for k in keys):
            raise ValueError("integer candidate transport counters required")
        capacity = 3 if version in (5, 6) else 2
        if any(w["read_beats"] * 64 != w["read_bytes"] or
               not 0 < w["reader_pipeline_peak"] <= capacity or
               not 0 < w["publisher_pipeline_peak"] <= capacity for w in row["workers"]):
            raise ValueError("candidate beat/pipeline ledger failed")
        if version == 6:
            keys = ("extent_beats", "directory_beats", "pma_beats", "rows", "empty_rows")
            if any(type(w.get(k)) is not int or w[k] < 0 for w in row["workers"] for k in keys) or any(
                    w["extent_beats"] != 1 or not 0 < w["directory_beats"] or
                    w["pma_beats"] * 16 != w["physical_slots"] or
                    sum(w[k] for k in keys[:3]) != w["read_beats"] or
                    not w["empty_rows"] <= w["rows"] for w in row["workers"]):
                raise ValueError("current input directory/PMA beat/row ledger failed")
        transport = row.get("transport", {})
        keys = ("accepted_beats", "intents", "grants", "consumed_grants", "request_waits",
                "contended_cycles", "capacity_blocked_cycles", "max_contenders")
        if any(type(transport.get(k)) is not int or transport[k] < 0 for k in keys):
            raise ValueError("integer shared transport counters required")
        if any(transport[k] * 64 != row["read_bytes"] for k in
               ("accepted_beats", "intents", "grants", "consumed_grants")) or transport[
                "request_waits"] != sum(w["backend_submit_stalls"] for w in row["workers"]):
            raise ValueError("candidate shared arbitration ledger failed")
    return row


def summarize(rows, reference):
    matrix = {(latency, reverse) for latency in (64, 128) for reverse in (0, 1)}
    if len(rows) != 4 or {(r["latency"], r["reverse"]) for r in rows} != matrix:
        raise ValueError("complete candidate matrix required")
    summary = []
    for latency in (64, 128):
        selected = [r["observations"] for r in rows if r["latency"] == latency]
        if selected[0] != selected[1]:
            raise ValueError("candidate registration order changes results")
        controls = [r["observations"] for r in reference
                    if r["arm"] == "a4_io16" and r["latency"] == latency]
        if len(controls) != 2 or controls[0] != controls[1]:
            raise ValueError("strong original A4 reference required")
        old = controls[0]["result"]
        rounds = old["rounds"]
        if rounds != 46:
            raise ValueError("same convergence scope required")
        cycles = selected[0]["cycles"] * rounds
        summary.append(dict(latency=latency, scans=rounds,
            reader_only_scan_cycles=selected[0]["cycles"], unchanged_scans_cycles=cycles,
            original_a4_complete_cycles=old["cycles"],
            reader_floor_over_a4=cycles / old["cycles"],
            integrated_r_retention_passed=False, hardware_calibrated=False))
    if not all(math.isfinite(r["reader_floor_over_a4"]) for r in summary):
        raise ValueError("nonfinite candidate comparison")
    return dict(rows=summary, claim="experimental_reader_only_not_integrated_R_or_hardware")
