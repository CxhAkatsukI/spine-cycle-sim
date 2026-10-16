"""Independent output/guard checks and overlap-aware measured event windows."""

import math
from pathlib import Path
import statistics

from .. import artifact, control_analysis, oracle
from ..source_build.configuration import CLOCK_MHZ
from .preparation import GRAPHS, REPEATS

PASS = "ORIGINAL_R_11L3B_GUARDED_BOARD_MATRIX_PASS_NOT_PUBLICATION_MATCH"
METRICS = {"status", "board_programmed", "hardware_timing_measured", "bdf", "events",
           "enqueue_to_completion_ms", "event_union_ns", "event_span_ns"}


def event_window(events):
    if not isinstance(events, list) or not events:
        raise ValueError("nonempty kernel events required")
    intervals = []
    for event in events:
        if not isinstance(event, dict):
            raise ValueError("structured kernel event required")
        times = [event.get(name) for name in ("queued_ns", "submitted_ns", "start_ns", "end_ns")]
        if (any(type(value) is not int or not 0 <= value < 2**64 for value in times) or
                not times[0] <= times[1] <= times[2] < times[3]):
            raise ValueError("invalid raw kernel event timestamps")
        intervals.append((times[2], times[3]))
    intervals.sort()
    end, busy = intervals[0][0], 0
    for start, stop in intervals:
        busy += max(0, stop - max(start, end))
        end = max(end, stop)
    return busy, end - intervals[0][0]


def inspect(observed, output, case, bdf):
    if (observed.get("status") != "ORIGINAL_R_GUARDED_BOARD_CONTROL_PASS" or
            observed.get("board_programmed") is not True or observed.get("hardware_timing_measured") is not True or
            observed.get("publication_match") is not False or observed.get("bdf") != bdf):
        raise ValueError("explicit guarded board success on the leased BDF required")
    offline = case["offline"]
    if {key: value for key, value in observed.items() if key not in METRICS} != \
            {key: value for key, value in offline.items() if key not in METRICS}:
        raise ValueError("board semantics or geometry differs from admitted offline control")
    # Reuse only the geometry/oracle validator; measured evidence keeps its board label.
    oracle_view = {**observed, **{key: offline[key] for key in METRICS}}
    independent = control_analysis.inspect(oracle_view, output, case["reference"])
    if independent != case["expected"]:
        raise ValueError("board expectation differs from independent audited oracle")
    pins = [artifact.identity(output / "expected.u32le"), artifact.identity(output / "result.json")]
    for lane in range(14):
        pin = artifact.identity(output / f"replica{lane}.u32le")
        if pin["sha256"] != independent["expected_sha256"]:
            raise ValueError("replica output, publication padding, tail or guard differs")
        pins.append(pin)
    descriptor = oracle.read_words(Path(case["input"]) / "mixed.u32le", 12 + 8 * offline["tasks"])
    if list(descriptor[:2]) != [0x4D47524F, 1] or list(descriptor[10:12]) != [11, 3]:
        raise ValueError("original 11+3 task descriptor required")
    expected = [("hbm_wrapper", 0, 0), ("apply", 0, 0)]
    for ordinal in range(offline["tasks"]):
        lane = descriptor[12 + 8 * ordinal + 2]
        expected.append(("little" if lane < 11 else "big", ordinal, lane))
    events = observed["events"]
    if (not isinstance(events, list) or any(not isinstance(event, dict) or
            any(type(event.get(name)) is not int for name in ("ordinal", "lane")) for event in events)):
        raise ValueError("integer kernel event identities required")
    if [(event.get("role"), event.get("ordinal"), event.get("lane")) for event in events] != expected:
        raise ValueError("missing, duplicate or reassigned kernel profiling event")
    busy, span = event_window(events)
    wall = observed["enqueue_to_completion_ms"]
    if (type(wall) not in (int, float) or not math.isfinite(wall) or wall <= 0 or
            type(observed["event_union_ns"]) is not int or type(observed["event_span_ns"]) is not int or
            (busy, span) != (observed["event_union_ns"], observed["event_span_ns"]) or span > math.ceil(wall * 1e6)):
        raise ValueError("recorded event union/span or resident wall window differs")
    return {"independent_oracle": independent, "enqueue_to_completion_ms": wall,
            "event_union_ns": busy, "event_span_ns": span,
            "event_span_cycles_at_implemented_clock": span * CLOCK_MHZ / 1000,
            "clock_mhz": CLOCK_MHZ, "pins": pins}


def matrix(rows):
    expected = {(graph, binding, repeat) for graph in GRAPHS
                for binding in control_analysis.BINDINGS for repeat in range(REPEATS)}
    if len(rows) != len(expected) or {(row["graph"], row["binding"], row["repeat"]) for row in rows} != expected:
        raise ValueError("all eighteen predeclared board controls required")
    summaries = []
    for graph in GRAPHS:
        for binding in control_analysis.BINDINGS:
            selected = [row["analysis"] for row in rows if row["graph"] == graph and row["binding"] == binding]
            if len({row["independent_oracle"]["expected_sha256"] for row in selected}) != 1:
                raise ValueError("repeated board outputs differ")
            summaries.append({"graph": graph, "binding": binding, "repeats": REPEATS,
                **{metric: {"minimum": min(row[metric] for row in selected),
                            "median": statistics.median(row[metric] for row in selected),
                            "maximum": max(row[metric] for row in selected)}
                   for metric in ("enqueue_to_completion_ms", "event_union_ns", "event_span_ns")}})
    return summaries
