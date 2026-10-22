"""Admit a finite source loader only after unchanged controls and full states."""

import json

from ..analysis import parse_demo
from . import compact_analysis
from .analysis import identity

ARMS = (*compact_analysis.ARMS, "prefetch_source")
MATRIX = [(latency, reverse, arm) for latency in (64, 128)
          for reverse in (0, 1) for arm in ARMS]


def summarize(rows, reference, *, before):
    if [identity(row) for row in rows] != MATRIX:
        raise ValueError("complete sixteen-row source-overlap matrix required")
    if [identity(row) for row in before] != compact_analysis.MATRIX:
        raise ValueError("complete twelve-row pre-edit compact reference required")
    controls = [row for row in rows if row["arm"] != "prefetch_source"]
    legacy = compact_analysis.summarize(controls, reference)
    if any(first[field] != second[field] for first, second in zip(controls, before)
           for field in ("observations", "outputs")):
        raise ValueError("pre-edit controls changed cycles, traffic, state or trajectory")
    indexed = {identity(row): row for row in rows}
    comparisons = []
    for latency in (64, 128):
        pair = [indexed[(latency, reverse, "prefetch_source")] for reverse in (0, 1)]
        if any(pair[0][field] != pair[1][field] for field in ("observations", "outputs")):
            raise ValueError("source-overlap result depends on registration order")
        baseline = indexed[(latency, 0, "a4_io16")]
        old = indexed[(latency, 0, "prefetch_compact")]
        for candidate in pair:
            observation = candidate["observations"]
            result = observation["result"]
            records = ["DEMO_ROUND " + json.dumps(part) for part in observation["trajectory"]]
            parse_demo("\n".join(records + ["DEMO_RESULT " + json.dumps(result)]))
            if result["arm"] != "prefetch_source":
                raise ValueError("source-overlap arm differs from the declared candidate")
            if (compact_analysis.state_identity(candidate) != compact_analysis.state_identity(baseline) or
                    [part["active"] for part in observation["trajectory"]] !=
                    [part["active"] for part in baseline["observations"]["trajectory"]]):
                raise ValueError("source-overlap convergence semantics differ from A4")
            for field in ("read_bytes", "write_bytes"):
                if type(result.get(field)) is not int or result[field] != old["observations"]["result"][field]:
                    raise ValueError("source-overlap changed the physical traffic ledger")
        current = pair[0]["observations"]["result"]
        ratio = current["cycles"] / baseline["observations"]["result"]["cycles"]
        comparisons.append({"latency": latency, "candidate": current,
            "source_over_a4_io16": ratio,
            "cycle_reduction_from_compact": 1 - current["cycles"] / old["observations"]["result"]["cycles"],
            "within_ten_percent": abs(ratio - 1) <= 0.1})
    return {**legacy, "pre_edit_controls_replayed_exactly": 12, "comparisons": comparisons,
            "retention_pass": all(row["within_ten_percent"] for row in comparisons)}
