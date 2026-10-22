"""Admit complete compact-input controls, never infer a hardware timing match."""

import json

from ..analysis import parse_demo
from .analysis import MATRIX as REFERENCE_MATRIX, identity

ARMS = ("a4_io16", "bank_stream", "prefetch_compact")
MATRIX = [(latency, reverse, arm) for latency in (64, 128)
          for reverse in (0, 1) for arm in ARMS]


def state_identity(row):
    outputs = row["outputs"]
    expected = ([f"replica{i}.u32le" for i in range(4)] if row["arm"] == "a4_io16"
                else ["primary.u32le", "replica0.u32le", "replica1.u32le"])
    states = {(p["sha256"], p["bytes"]) for p in outputs}
    if ([p["name"] for p in outputs] != expected or len(states) != 1 or
            row["observations"]["result"]["replicas"] != len(expected)):
        raise ValueError("missing, extra or inconsistent full-state replicas")
    state = next(iter(states))
    if type(state[1]) is not int or state[1] <= 0 or state[1] % 4:
        raise ValueError("invalid full-state replica length")
    return state


def summarize(rows, reference):
    if [identity(row) for row in rows] != MATRIX:
        raise ValueError("complete twelve-row convergence matrix required")
    if [identity(row) for row in reference] != REFERENCE_MATRIX:
        raise ValueError("complete frozen 32-row reference required")
    observed = {identity(row): row for row in rows}
    old = {identity(row): row for row in reference}
    states = {}
    for key, row in observed.items():
        observation = row["observations"]
        records = ["DEMO_ROUND " + json.dumps(part) for part in observation["trajectory"]]
        records.append("DEMO_RESULT " + json.dumps(observation["result"]))
        parse_demo("\n".join(records))
        result = observation["result"]
        if result["arm"] != row["arm"] or any(type(result.get(field)) is not int or result[field] < 0
                for field in ("read_bytes", "write_bytes")):
            raise ValueError("invalid arm or physical traffic ledger")
        states[key] = state_identity(row)
        if row["arm"] != "prefetch_compact" and any(
                row[field] != old[key][field] for field in ("observations", "outputs")):
            raise ValueError("legacy cycles, traffic, state or trajectory changed")
    comparisons = []
    for latency in (64, 128):
        for arm in ARMS:
            first, second = (observed[(latency, reverse, arm)] for reverse in (0, 1))
            if any(first[field] != second[field] for field in ("observations", "outputs")):
                raise ValueError("result depends on component registration order")
        candidate = observed[(latency, 0, "prefetch_compact")]
        baseline = observed[(latency, 0, "a4_io16")]
        if (states[identity(candidate)] != states[identity(baseline)] or
                [r["active"] for r in candidate["observations"]["trajectory"]] !=
                [r["active"] for r in baseline["observations"]["trajectory"]]):
            raise ValueError("compact convergence semantics differ from A4")
        values = {arm: observed[(latency, 0, arm)]["observations"]["result"] for arm in ARMS}
        ratio = values["prefetch_compact"]["cycles"] / values["a4_io16"]["cycles"]
        comparisons.append({"latency": latency, "arms": values, "compact_over_a4_io16": ratio,
                            "within_ten_percent": abs(ratio - 1) <= 0.1})
    return {"legacy_rows_replayed_exactly": 8, "comparisons": comparisons,
            "retention_pass": all(row["within_ten_percent"] for row in comparisons),
            "hardware_timing_admitted": False, "publication_match_admitted": False,
            "strict_resource_match_admitted": False, "production_baseline_admitted": False,
            "new_spine_comparison_executed": False}
