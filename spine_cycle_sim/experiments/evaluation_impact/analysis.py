"""Admission of complete diagnostic matrices, without publication-match claims."""

import json


ARMS = ("a4", "cross_row", "candidate")
MATRIX = [(latency, reverse, arm) for latency in (64, 128)
          for reverse in (0, 1) for arm in ARMS]


def parse_demo(text):
    rounds, results = [], []
    for line in text.splitlines():
        tag, separator, value = line.partition(" ")
        if not separator or tag not in ("DEMO_ROUND", "DEMO_RESULT"):
            raise ValueError("unknown demo observation")
        (rounds if tag == "DEMO_ROUND" else results).append(json.loads(value))
    if len(results) != 1:
        raise ValueError("unique demo result required")
    result = results[0]
    if result.get("passed") is not True or len(rounds) != result["rounds"] or not rounds:
        raise ValueError("complete converged trajectory required")
    if [r["round"] for r in rounds] != list(range(len(rounds))) or rounds[-1]["active"] != 0:
        raise ValueError("nonconverged or unordered trajectory")
    if any(r["arm"] != result["arm"] or type(r["cycles"]) is not int or r["cycles"] <= 0
           or type(r["active"]) is not int or r["active"] < 0 for r in rounds):
        raise ValueError("invalid round fields")
    if sum(r["cycles"] for r in rounds) != result["cycles"]:
        raise ValueError("round windows do not close")
    return {"result": result, "trajectory": rounds}


def summarize(rows):
    if [(r["latency"], r["reverse"], r["arm"]) for r in rows] != MATRIX:
        raise ValueError("complete predeclared R matrix required")
    for latency in (64, 128):
        group = [r for r in rows if r["latency"] == latency]
        for arm in ARMS:
            pair = [r for r in group if r["arm"] == arm]
            if pair[0]["observations"] != pair[1]["observations"] or pair[0]["outputs"] != pair[1]["outputs"]:
                raise ValueError("registration order changed observed behavior")
        trajectories = [[p["active"] for p in r["observations"]["trajectory"]] for r in group]
        states = [{p["sha256"] for p in r["outputs"]} for r in group]
        if any(t != trajectories[0] for t in trajectories) or any(s != states[0] for s in states):
            raise ValueError("arms differ in convergence/state")
    comparisons = []
    for latency in (64, 128):
        values = {r["arm"]: r["observations"]["result"] for r in rows
                  if r["latency"] == latency and r["reverse"] == 0}
        comparisons.append({"latency": latency, "arms": values,
            "candidate_over_a4": values["candidate"]["cycles"] / values["a4"]["cycles"],
            "cross_row_over_candidate": values["cross_row"]["cycles"] / values["candidate"]["cycles"],
            "candidate_over_cross_row_read_bytes": values["candidate"]["read_bytes"] / values["cross_row"]["read_bytes"]})
    return {"status": "R_CONVERGENCE_DIAGNOSTIC_PASS_NOT_BASELINE_ADMISSION", "comparisons": comparisons,
        "ten_percent_compute_target_met": all(0.9 <= r["candidate_over_a4"] <= 1.1 for r in comparisons),
        "hardware_timing_admitted": False, "publication_match_admitted": False,
        "strict_resource_match_admitted": False, "complete_spine_gr_comparison": False}
