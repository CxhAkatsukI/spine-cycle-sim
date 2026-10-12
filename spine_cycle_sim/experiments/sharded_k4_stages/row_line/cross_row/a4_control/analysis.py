"""Admit full state and physical work; cycle ratios remain predictions."""

import json
from pathlib import Path

from spine_cycle_sim.experiments.campaign_runtime import sha256_file
from spine_cycle_sim.experiments.original_regraph_validation.analysis import same_typed
from ...a4_control.analysis import exact_pair, output_signatures
from .contract import ARMS, LIMITS, STATUS, metadata, run_specs


def basis_case(basis, mode, latency, reverse, arm):
    return next(c for c in basis["cases"] if (c["mode"], c["latency"], c["reverse"], c["arm"])
                == (mode, latency, reverse, arm))


def admit(stdout, state, geometry, basis, spec):
    mode, latency, reverse, arm = spec
    original = basis_case(basis, mode, latency, reverse, "original")
    if arm == "original":
        return exact_pair(stdout, state, geometry, original)
    rows = [line.partition(" ")[::2] for line in stdout.splitlines()]
    groups = {key: [json.loads(value) for label, value in rows if label == key]
              for key in ("MODEL_CONTROL", "REAL_ROUND", "INVOCATION")}
    if (len(rows) != sum(len(items) for items in groups.values())
            or not same_typed(groups["MODEL_CONTROL"], [metadata(arm)])):
        raise ValueError("unknown output or model declaration differs")
    if len(groups["REAL_ROUND"]) != 1:
        raise ValueError("missing or duplicate counters")
    counters = groups["REAL_ROUND"][0]
    reference = basis_case(basis, mode, latency, reverse, "whole_line")
    expected = dict(reference["counters"])
    if arm == "cross_row":
        expected["cycles"] = counters.get("cycles")
    if (type(counters.get("cycles")) is not int or not 0 < counters["cycles"] <= LIMITS["max_cycles"]
            or not same_typed(counters, expected)):
        raise ValueError("exact reference replay or candidate conserved traffic differs")
    outputs = []
    for item in reference["outputs"]:
        path = state / Path(item["path"]).name
        if (path.is_symlink() or path.stat().st_size != geometry["padded_vertices"] * 4
                or sha256_file(path) != item["sha256"]):
            raise ValueError("complete candidate state differs from oracle")
        outputs.append({**item, "path": str(path)})
    if {p.name for p in state.iterdir()} != {Path(item["path"]).name for item in outputs}:
        raise ValueError("unexpected or missing state replica")
    invocations = groups["INVOCATION"]
    keys = []
    for row in invocations:
        if (row.keys() != {"round", "partition", "worker", "adapter", "start", "end"}
                or type(row["adapter"]) is not bool
                or any(type(row[key]) is not int for key in row if key != "adapter")
                or row["round"] != 1 or not 0 <= row["partition"] < 4
                or row["worker"] != row["partition"] % 4
                or not 0 <= row["start"] < row["end"] <= counters["cycles"]):
            raise ValueError("invalid partition invocation bounds")
        keys.append((row["partition"], row["adapter"]))
    if sorted(keys) != sorted((p, a) for p in range(4) for a in (False, True)):
        raise ValueError("missing or duplicate worker invocation")
    if arm == "whole_line" and not same_typed(invocations, reference["invocations"]):
        raise ValueError("exact reference invocation replay differs")
    return {"counters": counters, "outputs": outputs, "invocations": invocations,
            "k4_over_A4_cycles_diagnostic_only": counters["cycles"] / original["paths"][0]["cycles"],
            "whole_line_over_candidate_cycles_diagnostic_only": reference["counters"]["cycles"] / counters["cycles"]}


def matrix(cases):
    if [(c["mode"], c["latency"], c["reverse"], c["arm"]) for c in cases] != run_specs():
        raise ValueError("predeclared cross-row matrix incomplete or reordered")
    for mode, latency in (("cold", 64), ("warm_update", 64), ("warm_update", 128)):
        for arm in ARMS:
            pair = [c for c in cases if (c["mode"], c["latency"], c["arm"]) == (mode, latency, arm)]
            values = [{k: v for k, v in c.items() if k not in {"reverse", "outputs"}} for c in pair]
            if not same_typed(*values) or output_signatures(pair[0]["outputs"]) != output_signatures(pair[1]["outputs"]):
                raise ValueError("registration order changed complete result")
    for arm in ARMS[1:]:
        low, high = [c for c in cases if c["mode"] == "warm_update" and not c["reverse"] and c["arm"] == arm]
        if (high["counters"]["cycles"] <= low["counters"]["cycles"]
                or {k: v for k, v in high["counters"].items() if k != "cycles"} != {
                    k: v for k, v in low["counters"].items() if k != "cycles"}
                or output_signatures(low["outputs"]) != output_signatures(high["outputs"])):
            raise ValueError("memory sensitivity changed state or work")
    return {"status": STATUS, "runs": len(cases), "scenario_keys": 6,
            "exact_original_A4_and_legacy_replay": True, "exact_whole_line_replay": True,
            "cross_row_full_state_and_traffic": True, "registration_order_identical": True,
            "hardware_timing_admitted": False, "strict_resource_match_admitted": False,
            "publication_match_admitted": False, "convergence_comparison": False}
