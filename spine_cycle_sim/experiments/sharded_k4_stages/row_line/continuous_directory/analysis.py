"""Strict frozen replay and candidate state/work checks; timing is predicted."""

import json
from pathlib import Path

from spine_cycle_sim.experiments.campaign_runtime import sha256_file
from spine_cycle_sim.experiments.original_regraph_validation.analysis import same_typed
from ..cross_row.a4_control.analysis import basis_case


def records(text):
    groups = {}
    for line in text.splitlines():
        label, separator, payload = line.partition(" ")
        if not separator or label not in {"MODEL_CONTROL", "REAL_ROUND", "INVOCATION"}:
            raise ValueError("unexpected executor output")
        groups.setdefault(label, []).append(json.loads(payload))
    return groups


def admit(text, state, basis, mode, latency, reverse, arm, historical_text):
    if arm not in {"original", "cross_row", "continuous"}:
        raise ValueError("unknown experiment arm")
    old_arm = "original" if arm == "original" else "cross_row"
    old = basis_case(basis, mode, latency, reverse, old_arm)
    groups = records(text)
    if arm == "original":
        if not same_typed(groups, records(historical_text)):
            raise ValueError("original A4/legacy numerical replay changed")
    else:
        metadata = {"version": "continuous_directory_v1", "continuous_directory": int(arm == "continuous"),
                    "cross_row_pipeline": 1, "row_line_reads": 1, "fixed_rounds": 1,
                    "hardware_timing_admitted": False, "strict_resource_match_admitted": False}
        if (set(groups) != {"MODEL_CONTROL", "REAL_ROUND", "INVOCATION"}
                or not same_typed(groups.get("MODEL_CONTROL"), [metadata])
                or len(groups["REAL_ROUND"]) != 1):
            raise ValueError("candidate declaration or counter cardinality differs")
        expected = dict(old["counters"])
        counters = groups["REAL_ROUND"][0]
        if arm == "continuous":
            if type(counters.get("cycles")) is not int or not 0 < counters["cycles"] <= 100000000:
                raise ValueError("invalid bounded candidate cycle count")
            expected["cycles"] = counters["cycles"]
        if not same_typed(expected, counters):
            raise ValueError("frozen replay or candidate physical work changed")
        invocations = groups.get("INVOCATION", [])
        fields = {"round", "partition", "worker", "adapter", "start", "end"}
        if (len(invocations) != 8 or any(set(row) != fields
                or type(row["adapter"]) is not bool
                or any(type(row[key]) is not int for key in fields - {"adapter"})
                for row in invocations)
                or sorted((r["partition"], r["adapter"]) for r in invocations)
                != sorted((p, a) for p in range(4) for a in (False, True))):
            raise ValueError("missing worker invocation")
        for row in invocations:
            if (row["worker"] != row["partition"] % 4 or row["round"] != 1
                    or not 0 <= row["start"] < row["end"] <= counters["cycles"]):
                raise ValueError("invalid worker invocation bounds")
        if arm == "cross_row" and not same_typed(invocations, old["invocations"]):
            raise ValueError("V3 invocation schedule changed")
    outputs = []
    for item in old["outputs"]:
        path = state / Path(item["path"]).name
        if (path.is_symlink() or path.stat().st_size != item["bytes"]
                or sha256_file(path) != item["sha256"]):
            raise ValueError("full-state oracle or replica changed")
        outputs.append({"path": path.name, "bytes": path.stat().st_size, "sha256": sha256_file(path)})
    if {p.name for p in state.iterdir()} != {item["path"] for item in outputs}:
        raise ValueError("unexpected state output")
    cycles = groups["REAL_ROUND"][0]["cycles"]
    a4 = basis_case(basis, mode, latency, reverse, "original")["paths"][0]["cycles"]
    v3 = basis_case(basis, mode, latency, reverse, "cross_row")["counters"]["cycles"]
    return {"mode": mode, "latency": latency, "reverse": reverse, "arm": arm,
            "cycles": cycles, "v3_over_candidate": v3 / cycles, "candidate_over_A4": cycles / a4,
            "records": groups, "outputs": outputs}


def validate_matrix(cases):
    expected = {(mode, latency, reverse, arm)
                for mode, latency in (("cold", 64), ("warm_update", 64), ("warm_update", 128))
                for reverse in (0, 1) for arm in ("original", "cross_row", "continuous")}
    keys = [(row["mode"], row["latency"], row["reverse"], row["arm"]) for row in cases]
    if (len(keys) != 18 or set(keys) != expected
            or any(type(row["reverse"]) is not int or type(row["latency"]) is not int for row in cases)):
        raise ValueError("predeclared matrix incomplete or unexpected")
    for mode, latency in (("cold", 64), ("warm_update", 64), ("warm_update", 128)):
        for arm in ("original", "cross_row", "continuous"):
            pair = [row for row in cases if (row["mode"], row["latency"], row["arm"]) == (mode, latency, arm)]
            if len(pair) != 2 or {row["reverse"] for row in pair} != {0, 1}:
                raise ValueError("predeclared matrix incomplete")
            if not same_typed({k: v for k, v in pair[0].items() if k != "reverse"},
                              {k: v for k, v in pair[1].items() if k != "reverse"}):
                raise ValueError("registration order changed complete result")
    low, high = [next(row for row in cases if row["mode"] == "warm_update"
                     and row["arm"] == "continuous" and row["reverse"] == 0
                     and row["latency"] == latency) for latency in (64, 128)]
    if high["cycles"] <= low["cycles"]:
        raise ValueError("memory latency sensitivity was bypassed")
