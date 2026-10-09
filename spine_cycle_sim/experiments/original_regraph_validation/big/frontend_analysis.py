"""Admit original Big protocol, finite resources and conserved read/cache work."""

from .analysis import records, positive_integer

STATUS = "FINITE_BIG_MEMORY_FRONTEND_PASS_TIMING_PREDICTED"


def analyze(text: str, contract: dict, comparison: bool = False) -> list[dict]:
    rows = records(text, "BIG_FRONTEND")
    names = [f"source_case{id}" for id in contract["source_cases"]] if comparison else contract["cases"]
    if [row.get("id") for row in rows] != names:
        raise ValueError("Big frontend matrix missing, reordered or duplicated")
    numeric = ("logical_requests", "reads", "cache_hits", "edge_bytes", "source_bytes", "capacity_stalls",
               "response_stalls", "scatter_stalls", "fork_stalls", "checked_tuples")
    for row in rows:
        if (not positive_integer(row.get("cycles")) or row["cycles"] > 1000000 or
                any(type(row.get(key)) is not int or row[key] < 0 for key in numeric) or
                row["reads"] == 0 or row["logical_requests"] != row["reads"] + row["cache_hits"] or
                row["source_bytes"] != row["reads"] * 64 or row["edge_bytes"] != row["checked_tuples"] * 8):
            raise ValueError("Big frontend extent/cycle/request/cache/byte gate failed")
    if comparison:
        if [row["checked_tuples"] for row in rows] != [count * 8 for count in contract["source_bursts"]]:
            raise ValueError("Big source comparison does not cover every original tuple")
        expected = {"cases": 6, "requests": sum(row["logical_requests"] + 1 for row in rows),
                    "response_words": sum(row["logical_requests"] + 1 for row in rows) * 16,
                    "tuple_words": sum(row["checked_tuples"] for row in rows) * 2}
        if records(text, "BIG_FRONTEND_COMPARISON") != [expected]:
            raise ValueError("Big original-source request/response/value comparison incomplete")
    else:
        reference = {key: value for key, value in rows[0].items() if key != "id"}
        if any({key: value for key, value in rows[index].items() if key != "id"} != reference for index in (1, 2)):
            raise ValueError("Big frontend reversal/reuse changed counters")
        by_id = {row["id"]: row for row in rows}
        if by_id["line_zero"]["reads"] != 1 or by_id["dummy_only"]["reads"] != 1 or (
                by_id["duplicate_lines"]["cache_hits"] <= by_id["duplicate_lines"]["reads"]):
            raise ValueError("Big compulsory-line and wrapper-cache controls missing")
        if any(by_id[name]["cycles"] <= rows[0]["cycles"] for name in ("latency128", "outstanding1", "live1", "depth1_slow_sink")) or (
                by_id["live1"]["capacity_stalls"] <= rows[0]["capacity_stalls"] or
                by_id["depth1_slow_sink"]["scatter_stalls"] == 0 or by_id["depth1_slow_sink"]["fork_stalls"] == 0):
            raise ValueError("Big finite memory/credit/backpressure gate missing")
        if records(text, "BIG_FRONTEND_REJECTIONS") != [{"checks": 8}]:
            raise ValueError("Big input/allocation/acknowledgement/lifecycle rejection checks missing")
    return rows
