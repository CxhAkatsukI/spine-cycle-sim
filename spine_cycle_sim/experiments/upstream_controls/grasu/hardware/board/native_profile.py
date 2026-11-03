"""Replay native update-only correctness and CU timing."""

from decimal import Decimal


ALGORITHM = "RESIDUAL_PR_PMA_NATIVE_SHARDED"
EVENTS = "GRASU_SHARDED_UPDATE_EVENTS"
ROLES = {"cache0", "cache1", "ddr0", "ddr1", "degree", "dispatch",
         "search0", "search1", "search2", "search3"}
ORACLE_FIELDS = ("status", "touched_segments", "checked_words", "pma_mismatches",
                 "degree_sources", "degree_mismatches")
NATIVE_ALGORITHMS = {"residual_pagerank": (ALGORITHM + "_INPUT", ALGORITHM),
                     "cc": ("CC_PMA_NATIVE_SHARDED_INPUT", "connected_components"),
                     "weighted_sssp": ("WEIGHTED_PMA_NATIVE_SHARDED_INPUT", "weighted_sssp")}


def fields(text):
    row = {}
    for token in text.split():
        key, value = token.split("=", 1)
        if key in row:
            raise ValueError(f"duplicate native field: {key}")
        row[key] = value
    return row


def records(log, tag):
    prefix = tag + " "
    return [fields(line[len(prefix):]) for line in log.splitlines() if line.startswith(prefix)]


def one(log, tag):
    row, = records(log, tag)
    return row


def ns(row, key):
    value = Decimal(row[key]) * 1_000_000
    if not value.is_finite() or value < 0 or value != value.to_integral_value():
        raise ValueError(f"not a nonnegative whole-nanosecond value: {key}")
    return int(value)


def event_profile(log, shards, *, roles=ROLES):
    if "GRASU_SHARDED_UPDATE_DIAGNOSTIC_EVENTS" in log:
        raise ValueError("unexpected additional diagnostic launch")
    repeat = one(log, "GRASU_SHARDED_UPDATE_REPEAT")
    if (repeat["repeat"], repeat["final"]) != ("0", "1"):
        raise ValueError("exactly one final update launch is required")
    rows = records(log, EVENTS)
    phases = records(log, EVENTS + "_PHASE")
    if ([int(row["shard"]) for row in rows] != shards
            or len(phases) != len(shards) * len(roles)):
        raise ValueError("missing, duplicate or out-of-order shard event envelope")
    elapsed = inter_shard = busy = 0
    for ordinal, row in enumerate(rows):
        shard_phases = [p for p in phases if p["shard"] == row["shard"]]
        selected = {p["cu"]: p for p in shard_phases}
        if len(shard_phases) != len(roles) or selected.keys() != roles:
            raise ValueError("incomplete or duplicated algorithm-specific CU envelope")
        intervals = []
        for cu, p in selected.items():
            start, end = ns(p, "start_offset_ms"), ns(p, "end_offset_ms")
            if not 0 < end - start == ns(p, "execute_ms") == ns(row, cu + "_ms"):
                raise ValueError("inconsistent native CU timestamps")
            intervals.append((start, end))
        gap, span = ns(row, "gap_from_previous_ms"), ns(row, "union_ms")
        if (ordinal == 0 and gap) or min(s for s, _ in intervals) or max(e for _, e in intervals) != span:
            raise ValueError("inconsistent native shard envelope")
        # Report the busy union separately. The measured elapsed envelope
        # retains both holes within a shard and host gaps between shards.
        covered_end = 0
        for start, end in sorted(intervals):
            busy += max(0, end - max(start, covered_end))
            covered_end = max(end, covered_end)
        elapsed += gap + span
        inter_shard += gap
    # The host's event_union_ms() is a first-to-last envelope, not a union.
    if not 0 < busy <= elapsed or elapsed != ns(repeat, "update_ms"):
        raise ValueError("computed elapsed envelope differs from native repeat record")
    return {"repeat": 0, "event_span_ns": elapsed, "busy_union_ns": busy,
            "inter_shard_gap_ns": inter_shard, "cu_events": len(phases)}


def update_only_profile(log, result, *, bdf, reference, algorithm="residual_pagerank"):
    settings = (
        ("GRASU_REGRAPH_DEVICE", "bdf", bdf),
        ("SHARDED_METADATA_POLICY", "replicas", "4"),
        ("SHARDED_INPUT_RESIDENCY", "policy", "premigrate"),
        ("GRASU_SHARDED_UPDATE_REPEAT_CONFIG", "repeats", "1"),
    )
    if any(one(log, tag)[key] != value for tag, key, value in settings):
        raise ValueError("wrong board, metadata layout, residency or repetitions")
    degree = algorithm == "residual_pagerank"
    input_tag, algorithm_name = NATIVE_ALGORITHMS[algorithm]
    config = one(log, input_tag)
    workloads = (("vertices", "vertices"), ("destination_partitions", "shards"),
                 ("logical_updates", "updates"), ("physical_updates", "updates"),
                 ("pma_slots_total", "pma_slots"))
    if any(int(config[key]) != reference[other] for key, other in workloads):
        raise ValueError("candidate did not execute the frozen G workload")
    layout = records(log, "GRASU_SHARDED_UPDATE_LAYOUT")
    shards = list(range(reference["shards"]))
    partition = 65536
    if ([int(r["shard"]) for r in layout] != shards
            or sum(int(r["updates"]) for r in layout) != reference["updates"]
            or sum(int(r["pma_slots"]) for r in layout) != int(config["pma_slots_total"])
            or any(int(r["destination_base"]) != s * partition
                   or int(r["destination_vertices"]) != min(partition, reference["vertices"] - s * partition)
                   or int(r["updates"]) <= 0 for s, r in enumerate(layout))):
        raise ValueError("candidate shard layout differs from the declared workload")
    checked = fields(result)
    reported = one(log, "GRASU_SHARDED_UPDATE_ONLY_RESULT")
    if degree:
        report_fields = dict(zip(ORACLE_FIELDS, ORACLE_FIELDS))
    else:
        report_fields = {"status": "status", "touched_segments": "touched_segments",
                         "checked_words": "checked_words", "mismatches": "pma_mismatches"}
    if (checked != {key: reported[field] for key, field in report_fields.items()}
            or checked["status"] != "PASS"
            or reported["algorithm"] != algorithm_name
            or reported["repeats"] != "1"
            or reported["measurement_window"] != "same_process_update_events"
            or int(reported["pma_mismatches"]) != 0
            or any(int(checked[key]) <= 0 for key in ("touched_segments", "checked_words"))
            or (degree and (int(checked["degree_mismatches"]) != 0 or int(checked["degree_sources"]) <= 0))):
        raise ValueError("candidate update oracle failed or disagrees with stdout")
    profile = event_profile(log, shards, roles=ROLES if degree else ROLES - {"degree"})
    if ns(reported, "update_ms") != profile["event_span_ns"]:
        raise ValueError("update-only total differs from the event envelope")
    return {**profile, "config": config, "layout": layout, "oracle": checked}
