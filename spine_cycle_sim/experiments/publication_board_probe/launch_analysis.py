"""Index launch diagnostics without treating unmatched rates as reproduction."""

import argparse
import json
from pathlib import Path
import statistics

from .launch import summarize
from .regraph import identity, save


def package(raw_path, output):
    raw = json.loads(raw_path.read_text())
    if (raw["status"] != "HOST_LAUNCH_DIAGNOSTIC_PASS_NOT_PUBLICATION_MATCH"
            or raw["publication_match"] is not False):
        raise ValueError("completed non-publication launch diagnostic required")
    expected = {("baseline", 0)} | {(mode, repeat)
        for mode in ("baseline", "prebound", "author_order") for repeat in (1, 2, 3)}
    rows = raw["rows"]
    if (len(rows) != len(expected) or {(row["mode"], row["repeat"]) for row in rows} != expected
            or any(row["independent_oracle_pass"] is not True for row in rows)):
        raise ValueError("complete correctness-passing launch matrix required")
    summaries = summarize(rows)
    if summaries != raw["summaries"]:
        raise ValueError("saved medians differ from raw repetitions")
    observations = []
    for row in rows:
        if row["mode"] != "baseline" or row["repeat"] == 0:
            continue
        lanes = {}
        little_ms = []
        for event in row["events"]:
            duration = (event["end_ns"] - event["start_ns"]) / 1e6
            if event["role"] == "little":
                little_ms.append(duration)
            elif event["role"] == "big":
                lanes.setdefault(event["lane"], []).append(duration)
        if len(little_ms) != 11 or len(lanes) != 3 or any(len(times) != 2 for times in lanes.values()):
            raise ValueError("expected eleven Little tasks and two waves on three Big lanes")
        observations.append({"repeat": row["repeat"], "event_span_ms": row["event_span_ms"],
            "longest_little_event_ms": max(little_ms),
            "longest_big_lane_event_sum_ms": max(sum(times) for times in lanes.values()),
            "longest_big_first_wave_event_ms": max(times[0] for times in lanes.values()),
            "longest_big_second_wave_event_ms": max(times[1] for times in lanes.values())})
    baseline = next(row for row in summaries if row["mode"] == "baseline")
    author = next(row for row in summaries if row["mode"] == "author_order")
    cold = next(row for row in rows if row["repeat"] == 0)
    result = {"status": raw["status"], "publication_match": False,
        "raw_report": identity(raw_path), "runner": raw["runner"], "source": raw["source"],
        "host": raw["host"], "xclbin": raw["xclbin"], "frozen_commit": raw["frozen_commit"],
        "manifest": raw["manifest"], "runtime": raw["runtime"], "scope": raw["scope"],
        "correctness_passing_executions": len(rows),
        "cold_baseline": {key: cold[key] for key in (
            "event_span_ms", "resident_wall_ms", "first_wave_start_spread_ms", "gteps")},
        "warm_medians": summaries,
        "warm_baseline_event_range_ms": [min(row["event_span_ms"] for row in rows
            if row["mode"] == "baseline" and row["repeat"] > 0), max(row["event_span_ms"] for row in rows
            if row["mode"] == "baseline" and row["repeat"] > 0)],
        "cold_over_warm_event_span_ratio": cold["event_span_ms"] / baseline["event_span_ms"],
        "author_timer_fraction_of_full_event_span": author["post_enqueue_wait_ms"] / author["event_span_ms"],
        "warm_baseline_timeline": observations,
        "warm_baseline_median_longest_big_lane_ms": statistics.median(
            row["longest_big_lane_event_sum_ms"] for row in observations),
        "timeline_limit": "CU lifetimes include stream/HBM waiting; these are not internal-stage counters.",
        "publication_reference": {"url": "https://soldierchen.github.io/assets/pdf/regraph.pdf",
            "version": "17-page MICRO 2022 camera-ready; not the local 13-page arXiv preprint",
            "table_iv_am_pr_system_gteps": 3.744, "table_iv_am_pr_best_gteps": 4.224,
            "figure_10_normalized_clock_mhz": 210,
            "same_configuration_match_established": False},
        "remaining_scope": "Current sharded K4 adapter+R and original G publication matches remain unestablished."}
    save(output, result)
    return result


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--raw", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    print(package(args.raw, args.output)["status"])
