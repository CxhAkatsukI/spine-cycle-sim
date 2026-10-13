"""Compare every declared sensitivity row and replay legacy observations exactly."""

import json

from ..analysis import MATRIX as LEGACY_MATRIX, parse_demo, summarize as legacy_summary

ARMS = ("a4", "cross_row", "candidate", "a4_io16", "candidate_apply2",
        "candidate_parents2", "candidate_both2")
MATRIX = [(latency, reverse, arm) for latency in (64, 128)
          for reverse in (0, 1) for arm in ARMS]


def identity(row):
    return row["latency"], row["reverse"], row["arm"]


def summarize(rows, reference):
    if [identity(row) for row in rows] != MATRIX:
        raise ValueError("complete predeclared 28-row sensitivity matrix required")
    legacy_summary(reference)
    observed = {identity(row): row for row in rows}
    for row in rows:
        observations = row["observations"]
        records = ["DEMO_ROUND " + json.dumps(part) for part in observations["trajectory"]]
        records.append("DEMO_RESULT " + json.dumps(observations["result"]))
        parse_demo("\n".join(records))
        if observations["result"]["arm"] != row["arm"]:
            raise ValueError("observed arm differs from declared arm")
        if any(type(observations["result"].get(key)) is not int or observations["result"][key] < 0
               for key in ("read_bytes", "write_bytes")):
            raise ValueError("nonnegative physical traffic ledger required")
    for expected in reference:
        actual = observed[identity(expected)]
        if (actual["observations"] != expected["observations"] or
                actual["outputs"] != expected["outputs"]):
            raise ValueError("legacy cycles/state/trajectory/traffic changed")
    comparisons = []
    for latency in (64, 128):
        state, trajectory = None, None
        for arm in ARMS:
            first, second = (observed[(latency, reverse, arm)] for reverse in (0, 1))
            if first["observations"] != second["observations"] or first["outputs"] != second["outputs"]:
                raise ValueError("registration order changed sensitivity result")
            output = first["outputs"]
            expected_names = (["replica" + str(i) + ".u32le" for i in range(4)] if arm.startswith("a4")
                              else ["primary.u32le", "replica0.u32le", "replica1.u32le"])
            if ([p["name"] for p in output] != expected_names or
                    len({(p["sha256"], p["bytes"]) for p in output}) != 1):
                raise ValueError("missing, extra or inconsistent full-state replicas")
            current = (output[0]["sha256"], output[0]["bytes"])
            active = [part["active"] for part in first["observations"]["trajectory"]]
            if state is not None and (state != current or trajectory != active):
                raise ValueError("sensitivity arm changed state or convergence semantics")
            state, trajectory = current, active
        values = {arm: observed[(latency, 0, arm)]["observations"]["result"] for arm in ARMS}
        comparisons.append({"latency": latency, "arms": values,
            "over_legacy_a4": {arm: values[arm]["cycles"] / values["a4"]["cycles"] for arm in ARMS},
            "over_a4_io16": {arm: values[arm]["cycles"] / values["a4_io16"]["cycles"] for arm in ARMS}})
    return {"status": "R_CREDIT_SENSITIVITY_COMPLETE_NOT_BASELINE_ADMISSION",
        "legacy_rows_replayed_exactly": len(LEGACY_MATRIX), "comparisons": comparisons,
        "strict_resource_match_admitted": False, "hardware_timing_admitted": False,
        "publication_match_admitted": False, "production_baseline_admitted": False,
        "new_spine_comparison_executed": False}
