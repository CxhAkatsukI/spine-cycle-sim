"""Complete-R checks shared by explicit finite input-port experiments."""

import json

from ..analysis import parse_demo
from .analysis import identity
from .compact_analysis import state_identity
from .source_overlap_analysis import MATRIX as BEFORE_MATRIX

ARMS = ("a4_io16", "prefetch_source", "prefetch_dual_elastic")
MATRIX = [(latency, reverse, arm) for latency in (64, 128)
          for reverse in (0, 1) for arm in ARMS]


def summarize(rows, _reference, *, before, arms=ARMS, before_matrix=BEFORE_MATRIX,
              physical_masters=None, reduction_key="cycle_reduction_from_source",
              candidate_traffic=None):
    matrix = [(latency, reverse, arm) for latency in (64, 128)
              for reverse in (0, 1) for arm in arms]
    if [identity(row) for row in rows] != matrix:
        raise ValueError("complete declared convergence matrix required")
    if [identity(row) for row in before] != before_matrix:
        raise ValueError("complete declared pre-edit reference required")
    previous = {identity(row): row for row in before}
    indexed = {identity(row): row for row in rows}
    for row in rows:
        key = identity(row)
        obs = row["observations"]
        parse_demo("\n".join(["DEMO_ROUND " + json.dumps(part) for part in obs["trajectory"]] +
                             ["DEMO_RESULT " + json.dumps(obs["result"])]))
        if obs["result"]["arm"] != row["arm"]:
            raise ValueError("candidate arm differs from declared configuration")
        if row["arm"] != arms[2] and any(
                row[field] != previous[key][field] for field in ("observations", "outputs")):
            raise ValueError("pre-edit cycles, traffic, state or trajectory changed")
        opposite = indexed[(row["latency"], 1 - row["reverse"], row["arm"])]
        if any(row[field] != opposite[field] for field in ("observations", "outputs")):
            raise ValueError("candidate result depends on registration order")
        original = indexed[(row["latency"], 0, "a4_io16")]
        if (state_identity(row) != state_identity(original) or
                [r["active"] for r in obs["trajectory"]] !=
                [r["active"] for r in original["observations"]["trajectory"]]):
            raise ValueError("full state or converged active trajectory differs from A4")
        if row["arm"] == arms[2]:
            old = previous[(row["latency"], row["reverse"], arms[1])]["observations"]["result"]
            if candidate_traffic is not None:
                candidate_traffic(obs["result"], old)
            else:
                for field in ("read_bytes", "write_bytes"):
                    if type(obs["result"].get(field)) is not int or obs["result"][field] != old[field]:
                        raise ValueError("candidate changed physical traffic")
    comparisons = []
    for latency in (64, 128):
        values = {arm: indexed[(latency, 0, arm)]["observations"]["result"] for arm in arms}
        ratio = values[arms[2]]["cycles"] / values[arms[0]]["cycles"]
        comparisons.append(dict(latency=latency, arms=values, candidate_over_a4=ratio,
            **{reduction_key: 1 - values[arms[2]]["cycles"] / values[arms[1]]["cycles"]},
            within_ten_percent=0.9 <= ratio <= 1.1))
    return dict(pre_edit_controls_replayed_exactly=8, comparisons=comparisons,
        retention_pass=all(row["within_ten_percent"] for row in comparisons),
        physical_masters=physical_masters if physical_masters is not None else
            {"a4_io16": 13, "prefetch_source": 7, "prefetch_dual_elastic": 11},
        hardware_timing_admitted=False, publication_match_admitted=False,
        strict_resource_match_admitted=False, production_baseline_admitted=False,
        new_spine_comparison_executed=False)
