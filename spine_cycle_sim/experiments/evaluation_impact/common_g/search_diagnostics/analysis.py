"""Admit read-only observations only after exact state/time/traffic replay."""

from ..search_concurrency.preparation import matrix as previous_matrix
from ..cached_hot.study import metadata
from .preparation import matrix


def key(row):
    return row["latency"], row["case"], row["updates"], row["arm"]


def validate_diagnostics(row):
    observation, detail = row["observation"], row["diagnostics"]
    cycles = observation["cycles"]
    original = row["arm"] == "original_forwarded"
    if not isinstance(cycles, int) or cycles <= 0 or not observation["state_pass"]:
        raise ValueError("invalid execution time or state")
    for name, size in (("search_done", 4), ("first_hot_update", 2), ("last_hot_update", 2),
                       ("hot_completed", 2), ("cache_loaded", 2), ("write_started", 2),
                       ("metadata_port_cycles", 4), ("metadata_full_cycles", 4), ("metadata_peak_parents", 4)):
        values = detail[name]
        if len(values) != size or any(type(value) is not int or value < 0 for value in values):
            raise ValueError("invalid diagnostic vector: " + name)
    for name in ("search_done", "cache_loaded", "write_started"):
        if any(not 0 < value <= cycles for value in detail[name]):
            raise ValueError("missing completion marker: " + name)
    if not 0 < detail["dispatch_done"] <= cycles or sum(detail["hot_completed"]) != observation["cache_updates"]:
        raise ValueError("diagnostic dispatch/update count mismatch")
    for first, last, count, loaded, written in zip(detail["first_hot_update"], detail["last_hot_update"],
            detail["hot_completed"], detail["cache_loaded"], detail["write_started"]):
        if (count == 0 and (first or last)) or (count > 0 and not loaded <= first <= last <= written <= cycles):
            raise ValueError("invalid cache marker order")
    ports = detail["ports"]
    if len({p["name"] for p in ports}) != len(ports) or len(ports) != (46 if original else 18):
        raise ValueError("unexpected/duplicate port topology")
    for field, result in (("read_bytes", "read_bytes"), ("write_bytes", "write_bytes")):
        if sum(p[field] for p in ports) != observation[result]:
            raise ValueError("diagnostic physical traffic mismatch")
    for port in ports:
        if port["requests"] != port["responses"] or port["beats_issued"] != port["beats_completed"]:
            raise ValueError("diagnostic requests not drained")
    expected_ports = 8 if original else 1
    summaries = []
    for index in range(4):
        selected = [p for p in ports if (p["name"].startswith(f"search{index}.table") if original
                                      else p["name"] == f"grasu-row{index}")]
        sampled, full, peak = (detail[name][index] for name in
            ("metadata_port_cycles", "metadata_full_cycles", "metadata_peak_parents"))
        if len(selected) != expected_ports or sampled != cycles * expected_ports or full > sampled or \
                peak > max(p["parent_limit"] for p in selected) + 1:
            raise ValueError("invalid metadata pressure observation")
        summaries.append({"cu": index, "ports": expected_ports, "full_fraction": full / sampled,
            "peak_parents_per_port": peak, "read_bytes": sum(p["read_bytes"] for p in selected),
            "backend_stalls": sum(p["backend_stalls"] for p in selected),
            "parent_stalls": sum(p["parent_stalls"] for p in selected)})
    return {"latency": row["latency"], "case": row["case"], "updates": row["updates"], "arm": row["arm"],
        "cycles": cycles, "last_search_cycle": max(detail["search_done"]),
        "last_hot_update_cycle": max(detail["last_hot_update"]),
        "first_write_cycle": min(detail["write_started"]),
        "last_write_start_cycle": max(detail["write_started"]),
        "cache_loaded": detail["cache_loaded"], "metadata": summaries}


def analyze(report, previous):
    for name, value in metadata().items():
        if name not in ("assumptions", "safety") and report.get(name) != value:
            raise ValueError("diagnostic resource/timing declaration changed")
    expected = set(matrix())
    if report["errors"] or len(report["rows"]) != len(expected) or set(map(key, report["rows"])) != expected or \
            len(report["matrix"]) != len(expected) or set(map(tuple, report["matrix"])) != expected:
        raise ValueError("complete unique diagnostic matrix required")
    if previous["status"] != "G_SEARCH_CONCURRENCY_VALIDATED_REFERENCE_TIMING_OPEN" or \
            len(previous["rows"]) != len(previous_matrix()) or set(map(key, previous["rows"])) != set(previous_matrix()):
        raise ValueError("complete frozen concurrency checkpoint required")
    if any(report.get(name, False) for name in
            ("baseline_admitted", "hardware_timing_admitted", "publication_match_admitted",
             "production_baseline_admitted", "reference_cache_timing_admitted")):
        raise ValueError("read-only diagnostics cannot promote baseline or hardware admission")
    old = {key(row): row for row in previous["rows"]}
    summaries = []
    for row in report["rows"]:
        prior = old[key(row)]
        if row["observation"] != prior["observation"] or row["state_sha256"] != prior["state_sha256"]:
            raise ValueError("read-only diagnostics changed state/time/traffic")
        summaries.append(validate_diagnostics(row))
    return {"exact_replayed_rows": len(summaries), "stage_observations": summaries,
        "complete_previous_performance_gate": previous["forwarded_reference_within_ten_percent_both_directions"],
        "hardware_timing_admitted": False, "baseline_admitted": False}
