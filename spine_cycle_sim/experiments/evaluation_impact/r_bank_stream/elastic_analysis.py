"""Complete-R admission for explicit dual readers and a third pipeline slot."""

import json

from ..analysis import parse_demo
from .analysis import identity
from .compact_analysis import state_identity
from .source_overlap_analysis import MATRIX as BEFORE_MATRIX

ARMS = ("a4_io16", "prefetch_source", "prefetch_dual_elastic")
MATRIX = [(latency, reverse, arm) for latency in (64, 128)
          for reverse in (0, 1) for arm in ARMS]


def summarize(rows, _reference, *, before):
    if [identity(row) for row in rows] != MATRIX:
        raise ValueError("complete twelve-row dual-elastic convergence matrix required")
    if [identity(row) for row in before] != BEFORE_MATRIX:
        raise ValueError("complete sixteen-row pre-edit source reference required")
    previous = {identity(row): row for row in before}
    indexed = {identity(row): row for row in rows}
    for row in rows:
        key = identity(row)
        obs = row["observations"]
        parse_demo("\n".join(["DEMO_ROUND " + json.dumps(part) for part in obs["trajectory"]] +
                             ["DEMO_RESULT " + json.dumps(obs["result"])]))
        if obs["result"]["arm"] != row["arm"]:
            raise ValueError("candidate arm differs from declared configuration")
        if row["arm"] != "prefetch_dual_elastic" and any(
                row[field] != previous[key][field] for field in ("observations", "outputs")):
            raise ValueError("pre-edit cycles, traffic, state or trajectory changed")
        opposite = indexed[(row["latency"], 1 - row["reverse"], row["arm"])]
        if any(row[field] != opposite[field] for field in ("observations", "outputs")):
            raise ValueError("dual-elastic result depends on registration order")
        original = indexed[(row["latency"], 0, "a4_io16")]
        if (state_identity(row) != state_identity(original) or
                [r["active"] for r in obs["trajectory"]] !=
                [r["active"] for r in original["observations"]["trajectory"]]):
            raise ValueError("full state or converged active trajectory differs from A4")
        if row["arm"] == "prefetch_dual_elastic":
            old = previous[(row["latency"], row["reverse"], "prefetch_source")]["observations"]["result"]
            for field in ("read_bytes", "write_bytes"):
                if type(obs["result"].get(field)) is not int or obs["result"][field] != old[field]:
                    raise ValueError("dual-elastic changed physical traffic")
    comparisons = []
    for latency in (64, 128):
        values = {arm: indexed[(latency, 0, arm)]["observations"]["result"] for arm in ARMS}
        ratio = values[ARMS[2]]["cycles"] / values[ARMS[0]]["cycles"]
        comparisons.append(dict(latency=latency, arms=values, candidate_over_a4=ratio,
            cycle_reduction_from_source=1 - values[ARMS[2]]["cycles"] / values[ARMS[1]]["cycles"],
            within_ten_percent=0.9 <= ratio <= 1.1))
    return dict(pre_edit_controls_replayed_exactly=8, comparisons=comparisons,
        retention_pass=all(row["within_ten_percent"] for row in comparisons),
        physical_masters={"a4_io16": 13, "prefetch_source": 7, "prefetch_dual_elastic": 11},
        hardware_timing_admitted=False, publication_match_admitted=False,
        strict_resource_match_admitted=False, production_baseline_admitted=False,
        new_spine_comparison_executed=False)
