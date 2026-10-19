"""Require all legacy fields unchanged before interpreting the new topology."""

import json

from ..analysis import MATRIX as ORIGINAL_MATRIX, parse_demo
from ..r_credits.analysis import ARMS as OLD_ARMS, MATRIX as OLD_MATRIX, identity
from ..r_credits.analysis import summarize as credit_summary

ARMS = (*OLD_ARMS, "bank_stream")
MATRIX = [(latency, reverse, arm) for latency in (64, 128)
          for reverse in (0, 1) for arm in ARMS]


def summarize(rows, reference):
    if [identity(row) for row in rows] != MATRIX:
        raise ValueError("complete predeclared 32-row bank-stream matrix required")
    if [identity(row) for row in reference] != OLD_MATRIX:
        raise ValueError("complete frozen 28-row reference required")
    observed = {identity(row): row for row in rows}
    for expected in reference:
        actual = observed[identity(expected)]
        if any(actual[key] != expected[key] for key in ("observations", "outputs")):
            raise ValueError("legacy cycles/state/trajectory/traffic changed")
    legacy = [observed[key] for key in OLD_MATRIX]
    original = [row for row in reference if identity(row) in ORIGINAL_MATRIX]
    credit_summary(legacy, original)
    comparisons = []
    for latency in (64, 128):
        first, second = (observed[(latency, reverse, "bank_stream")] for reverse in (0, 1))
        if any(first[key] != second[key] for key in ("observations", "outputs")):
            raise ValueError("registration order changed bank-stream result")
        observation = first["observations"]
        records = ["DEMO_ROUND " + json.dumps(part) for part in observation["trajectory"]]
        records.append("DEMO_RESULT " + json.dumps(observation["result"]))
        parse_demo("\n".join(records))
        result = observation["result"]
        if result["arm"] != "bank_stream" or any(
                type(result.get(key)) is not int or result[key] < 0
                for key in ("read_bytes", "write_bytes")):
            raise ValueError("bank-stream arm or physical traffic ledger invalid")
        control = observed[(latency, 0, "candidate")]
        if first["outputs"] != control["outputs"] or (
                [r["active"] for r in observation["trajectory"]] !=
                [r["active"] for r in control["observations"]["trajectory"]]):
            raise ValueError("bank-stream full-state replicas or convergence semantics changed")
        values = {arm: observed[(latency, 0, arm)]["observations"]["result"] for arm in ARMS}
        comparisons.append({"latency": latency, "arms": values,
            "bank_stream_over": {arm: result["cycles"] / values[arm]["cycles"] for arm in OLD_ARMS}})
    return {"status": "BANK_STREAM_CONVERGENCE_CONTROLS_COMPLETE_NOT_HARDWARE_ADMISSION",
        "legacy_rows_replayed_exactly": len(reference), "comparisons": comparisons,
        "strict_resource_match_admitted": False, "hardware_timing_admitted": False,
        "publication_match_admitted": False, "production_baseline_admitted": False,
        "new_spine_comparison_executed": False}
