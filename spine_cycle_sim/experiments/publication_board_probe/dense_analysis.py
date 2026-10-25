"""Compare complete numD=1/3 launch matrices on one unchanged FPGA artifact."""

import argparse
import json
from pathlib import Path

from .launch import summarize
from .regraph import identity, save


def inspect(raw, dense):
    expected = {("baseline", 0)} | {(mode, repeat) for mode in
        ("baseline", "prebound", "author_order") for repeat in (1, 2, 3)}
    rows, case = raw["rows"], raw["case"]
    shape = case["offline"]
    if (raw["status"] != "HOST_LAUNCH_DIAGNOSTIC_PASS_NOT_PUBLICATION_MATCH" or raw["publication_match"] is not False
            or dense not in (1, 3) or shape["dense"] != dense or (shape["little"], shape["big"]) != (11, 3)
            or case["binding"] != "author_initial" or len(rows) != len(expected)
            or {(row["mode"], row["repeat"]) for row in rows} != expected
            or any(row["independent_oracle_pass"] is not True for row in rows)):
        raise ValueError("complete passing numD=1/3 author-initial matrix required")
    medians = summarize(rows)
    if medians != raw["summaries"]:
        raise ValueError("saved warm medians differ from repetitions")
    timeline = []
    for row in rows:
        lanes = {}
        for event in row["events"]:
            lanes.setdefault((event["role"], event["lane"]), []).append(event)
        expected_lanes = {("little", lane): dense for lane in range(11)}
        expected_lanes.update({("big", lane): shape["sparse"] for lane in range(11, 14)})
        expected_lanes.update({("hbm_wrapper", 0): 1, ("apply", 0): 1})
        if {key: len(events) for key, events in lanes.items()} != expected_lanes:
            raise ValueError("task event counts differ from the author dense/sparse schedule")
        if row["mode"] == "baseline" and row["repeat"] > 0:
            durations = {key: [(event["end_ns"] - event["start_ns"]) / 1e6 for event in events]
                         for key, events in lanes.items()}
            timeline.append({"repeat": row["repeat"], "event_span_ms": row["event_span_ms"],
                "longest_little_lane_event_sum_ms": max(sum(value) for key, value in durations.items() if key[0] == "little"),
                "longest_big_lane_event_sum_ms": max(sum(value) for key, value in durations.items() if key[0] == "big")})
    cold = next(row for row in rows if row["repeat"] == 0)
    return {"numD": dense, "shape": shape, "correctness_passing_executions": len(rows),
            "cold_baseline": {key: cold[key] for key in ("event_span_ms", "resident_wall_ms", "gteps")},
            "warm_medians": medians, "warm_baseline_timeline": timeline,
            "warm_baseline_event_range_ms": [min(row["event_span_ms"] for row in timeline),
                                             max(row["event_span_ms"] for row in timeline)]}


def package(directory, output):
    prep_path = directory / "preparation.json"
    prep = json.loads(prep_path.read_text())
    if prep["status"] != "NUMD_INPUTS_ORACLE_PASS_NOT_FPGA" or [case["numD"] for case in prep["cases"]] != [1, 3]:
        raise ValueError("passing declared input preparation required")
    reports = []
    results = []
    for dense, prepared in zip((1, 3), prep["cases"]):
        path = directory / f"board_numd{dense}/results.json"
        raw = json.loads(path.read_text())
        if raw["case"] != prepared["case"]:
            raise ValueError("measured input differs from declared preparation")
        results.append({**inspect(raw, dense), "raw": identity(path), "runtime": raw["runtime"],
                        "host": raw["host"]})
        reports.append(raw)
    for key in ("xclbin", "source", "headers", "frozen_commit"):
        if reports[0][key] != reports[1][key]:
            raise ValueError("FPGA artifact or host source changed between numD controls")
    if (reports[0]["host"]["sha256"] != reports[1]["host"]["sha256"] or
            reports[0]["runtime"] != reports[1]["runtime"]):
        raise ValueError("host binary, board or runtime changed between numD controls")
    if (prep["cases"][0]["shared"] != prep["cases"][1]["shared"] or
            prep["cases"][0]["case"]["expected"]["logical_sha256"] !=
            prep["cases"][1]["case"]["expected"]["logical_sha256"]):
        raise ValueError("initial state or logical oracle differs between numD controls")
    baseline = [next(row for row in result["warm_medians"] if row["mode"] == "baseline") for result in results]
    report = {"status": "NUMD_BOARD_COMPARISON_PASS_NOT_PUBLICATION_MATCH", "publication_match": False,
        "preparation": identity(prep_path), "graph": prep["graph"], "source": reports[0]["source"],
        "xclbin": reports[0]["xclbin"], "admission_patch": prep["admission_patch"], "cases": results,
        "numd3_over_numd1_throughput": baseline[1]["gteps"] / baseline[0]["gteps"],
        "timing_boundary": reports[0]["device_window"], "clock_mhz": 150,
        "scope": prep["scope"], "timeline_limit": "CU lifetimes include waiting; no internal-stage attribution.",
        "publication_reference": {"url": "https://soldierchen.github.io/assets/pdf/regraph.pdf",
            "table_iv_am_pr_system_gteps": 3.744, "table_iv_am_pr_best_gteps": 4.224,
            "appendix_amazon_command_numD": 3, "same_configuration_match_established": False}}
    save(output, report)
    return report


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--directory", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    print(json.dumps(package(args.directory, args.output), indent=2))
