"""Strict numerical and finite-pressure gates; never admit publication timing."""

import json

from spine_cycle_sim.experiments.original_regraph_validation.analysis import same_typed

STATUS = "FINITE_BIG_ROUTING_GATHER_PASS_TIMING_PREDICTED"


def records(text: str, prefix: str) -> list[dict]:
    return [json.loads(line[len(prefix) + 1:]) for line in text.splitlines()
            if line.startswith(prefix + " ")]


def positive_integer(value) -> bool:
    return type(value) is int and value > 0


def analyze_tests(text: str, contract: dict) -> list[dict]:
    expected = {"clock_mhz": contract["clock_mhz"], "big": contract["big"], "big_vertices": contract["big_vertices"],
                "bank_rows": 32768, "forwarding_entries": 4, "timing": contract["timing"]}
    if not same_typed(records(text, "BIG_CONFIG"), [expected]):
        raise ValueError("Big model timing/geometry differs from fixed contract")
    rows = records(text, "BIG_CASE")
    if [row.get("id") for row in rows] != contract["cases"]:
        raise ValueError("Big matrix missing, reordered or duplicated")
    for row in rows:
        if (type(row.get("checked_words")) is not int or row["checked_words"] != contract["big_vertices"] or
                not positive_integer(row.get("cycles")) or row["cycles"] > 1000000 or
                any(type(row.get(key)) is not int or row[key] < 0
                    for key in ("output_stalls", "capacity_stalls"))):
            raise ValueError("invalid Big extent, cycles or counters")
    reference = {key: value for key, value in rows[0].items() if key != "id"}
    for index in (1, 3):
        if {key: value for key, value in rows[index].items() if key != "id"} != reference:
            raise ValueError("Big reversal/reuse changed numerical timing counters")
    if (rows[5]["cycles"] <= rows[0]["cycles"] or rows[5]["output_stalls"] == 0 or
            rows[5]["capacity_stalls"] == 0 or rows[6]["cycles"] <= rows[4]["cycles"] or
            rows[6]["capacity_stalls"] == 0):
        raise ValueError("Big finite pressure/in-flight resource gate missing")
    if not same_typed(records(text, "BIG_REJECTIONS"), [{"port_and_lifecycle_checks": 8, "wrong_bank": True}]):
        raise ValueError("Big port/lifecycle rejection gates missing")
    return rows


def analyze_comparison(text: str, contract: dict) -> list[dict]:
    rows = records(text, "BIG_COMPARISON")
    if [row.get("case") for row in rows] != contract["source_case_order"]:
        raise ValueError("Big original-source comparison matrix changed")
    if any(type(row.get("case")) is not int or
           type(row.get("checked_words")) is not int or row["checked_words"] != contract["big_vertices"] or
           not positive_integer(row.get("cycles")) for row in rows):
        raise ValueError("Big source comparison extent/cycles changed")
    if rows[0] != rows[-1]:
        raise ValueError("Big source-comparison reuse changed counters")
    if sum(row["checked_words"] for row in rows) != contract["checked_source_words"]:
        raise ValueError("Big source comparison incomplete")
    return rows
