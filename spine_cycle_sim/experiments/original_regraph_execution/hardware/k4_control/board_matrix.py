"""Keep unsupported cases visible and summarize only independently checked FPGA rows."""

import math
import statistics

from ..board_execution.preparation import REPEATS
from . import analysis, board_analysis
from .inputs import GRAPHS

PASS = "MATCHED_K4_A4_GUARDED_BOARD_MATRIX_PASS_NOT_PUBLICATION_MATCH"
METRICS = ("enqueue_to_completion_ms", "event_union_ns", "event_span_ns")


def unsupported(case, repeat):
    return {"graph": case["graph"], "binding": case["binding"], "repeat": repeat,
            "status": analysis.UNSUPPORTED, "board_programmed": False, "hardware_timing_measured": False,
            **{key: case["reference"][key] for key in ("duplicates", "first_duplicate")}}


def summarize(rows, cases):
    expected = {(graph, binding, repeat) for graph in GRAPHS
                for binding in analysis.BINDINGS for repeat in range(REPEATS)}
    if (len(rows) != len(expected) or any(type(row.get("repeat")) is not int for row in rows) or
            {(row["graph"], row["binding"], row["repeat"]) for row in rows} != expected):
        raise ValueError("all eighteen predeclared K4 board rows required, including unsupported inputs")
    summaries = []
    for case in cases:
        selected = [row for row in rows if row["graph"] == case["graph"] and row["binding"] == case["binding"]]
        if len(selected) != REPEATS:
            raise ValueError("three exact K4 repetitions required")
        summary = {"graph": case["graph"], "binding": case["binding"], "repeats": REPEATS}
        if case["status"] == analysis.UNSUPPORTED:
            if any(row != unsupported(case, row["repeat"]) for row in selected):
                raise ValueError("unsupported K4 row cannot contain a timing or programming claim")
            summary.update(status=analysis.UNSUPPORTED, duplicates=case["reference"]["duplicates"],
                           first_duplicate=case["reference"]["first_duplicate"])
        else:
            if any(row["status"] != board_analysis.PASS or row["analysis"]["values"] != case["expected"]["values"]
                   for row in selected):
                raise ValueError("each repeated K4 readback must match its independent expectation")
            for row in selected:
                measured = row["analysis"]
                if (any(type(measured.get(key)) is not int or measured[key] <= 0
                        for key in ("event_union_ns", "event_span_ns")) or
                        type(measured.get("enqueue_to_completion_ms")) not in (int, float) or
                        not math.isfinite(measured["enqueue_to_completion_ms"]) or
                        measured["enqueue_to_completion_ms"] <= 0 or
                        not measured["event_union_ns"] <= measured["event_span_ns"] <=
                        math.ceil(measured["enqueue_to_completion_ms"] * 1e6)):
                    raise ValueError("positive finite overlap-aware K4 board times required")
            summary.update(status=board_analysis.PASS, **{metric: {
                "minimum": min(row["analysis"][metric] for row in selected),
                "median": statistics.median(row["analysis"][metric] for row in selected),
                "maximum": max(row["analysis"][metric] for row in selected)} for metric in METRICS})
        summaries.append(summary)
    return summaries
