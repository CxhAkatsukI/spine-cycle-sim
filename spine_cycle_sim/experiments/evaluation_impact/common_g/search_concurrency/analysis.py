"""Validate exact historical replay before evaluating explicit concurrency controls."""

from ..cached_hot.analysis import analyze as analyze_cached
from ..cached_hot.preparation import PREVIOUS_ARMS as OLDEST_ARMS, matrix as old_matrix
from ..hot_lanes.analysis import LEDGERS
from .preparation import ARMS, CASES, PREVIOUS_ARMS, matrix


def analyze(report, previous):
    geometry = {"clock_mhz": 200, "banks": 4, "bank_credits": 32,
        "hot_cache_halves": 2, "hot_cache_bytes_per_half": 131072 * 64,
        "banks_per_half": 16, "bank_queue_depth": 2, "bank_pipeline_entries": 3,
        "bank_interval_cycles": 3, "bank_latency_cycles": 7,
        "search_contexts_per_cu": {"cached_hot": 16, "cached_hot64": 64,
            "original": 64, "original_forwarded": 64}}
    if any(report.get(key) != value for key, value in geometry.items()):
        raise ValueError("undeclared concurrency-control resource or timing geometry")
    expected = set(matrix())
    actual = [(r["latency"], r["case"], r["updates"], r["arm"]) for r in report["rows"]]
    if len(actual) != len(expected) or set(actual) != expected or \
            len(report["matrix"]) != len(expected) or set(map(tuple, report["matrix"])) != expected:
        raise ValueError("incomplete, duplicate, or undeclared search-concurrency matrix")
    old_ids = [(r["latency"], r["case"], r["updates"], r["arm"]) for r in previous["rows"]]
    if previous.get("status") != "CACHED_G_PREDICTION_VALIDATED_REFERENCE_TIMING_OPEN" or \
            len(old_ids) != len(old_matrix()) or set(old_ids) != set(old_matrix()):
        raise ValueError("complete frozen 190-row cached-G checkpoint required")
    keyed = {(r["latency"], r["case"], r["arm"]): r for r in report["rows"]}
    for old in previous["rows"]:
        current = keyed[(old["latency"], old["case"], old["arm"])]
        if current["observation"] != old["observation"] or current["state_sha256"] != old["state_sha256"]:
            raise ValueError("old prediction/state/traffic changed")
    old_report = {**report, "rows": [r for r in report["rows"] if r["arm"] in PREVIOUS_ARMS],
                  "matrix": old_matrix()}
    oldest = {"rows": [r for r in previous["rows"] if r["arm"] in OLDEST_ARMS]}
    analyze_cached(old_report, oldest)
    comparisons = []
    for latency in (64, 128):
        for name, count, _ in CASES:
            rows = [keyed[(latency, name, arm)] for arm in ARMS]
            if len({r["state_sha256"] for r in rows}) != 1:
                raise ValueError("concurrency control full state differs")
            values = {r["arm"]: r["observation"] for r in rows}
            for arm, source in (("original_forwarded", "original"), ("cached_hot64", "cached_hot")):
                value, control = values[arm], values[source]
                if value["arm"] != arm or value["state_pass"] is not True or \
                        value["timing_kind"] != "declared_prediction" or \
                        type(value["cycles"]) is not int or value["cycles"] <= 0:
                    raise ValueError("invalid concurrency-control identity or time")
                if any(value[field] != control[field] for field in ("read_bytes", "write_bytes") + LEDGERS):
                    raise ValueError("concurrency control changed logical work or physical traffic")
            cycles = {arm: value["cycles"] for arm, value in values.items()}
            comparisons.append({"latency": latency, "case": name, "updates": count,
                "cycles": cycles,
                "cached64_over_forwarded_original": cycles["cached_hot64"] / cycles["original_forwarded"],
                "cached64_over_legacy_original": cycles["cached_hot64"] / cycles["original"],
                "cached64_over_cached16": cycles["cached_hot64"] / cycles["cached_hot"],
                "forwarded_over_legacy_original": cycles["original_forwarded"] / cycles["original"]})
    nonempty = [r for r in comparisons if r["updates"]]
    return {"comparisons": comparisons, "old_checkpoint_exact_rows": len(previous["rows"]),
        "forwarded_reference_no_more_than_ten_percent_slower":
            all(r["cached64_over_forwarded_original"] <= 1.1 for r in nonempty),
        "forwarded_reference_within_ten_percent_both_directions":
            all(0.9 <= r["cached64_over_forwarded_original"] <= 1.1 for r in nonempty)}
