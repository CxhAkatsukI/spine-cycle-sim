"""Validate the full declared source-control scope without inventing cycle evidence."""

import re

from .preparation import CASES, MODES

PACKET = re.compile(r"^SEARCH_PIPELINE_PASS updates=(\d+) probes=(\d+) stalled=([01]) "
                    r"channels=(\d+) output_blocked=(\d+) host_vendor_keep_bits=(\d+)$", re.M)
SUMMARY = re.compile(r"^SEARCH_PIPELINE_FIXTURE_PASS updates=(\d+) probes=(\d+)$", re.M)


def parse(stdout, count, mode):
    if mode not in MODES or not isinstance(count, int) or count < 0:
        raise ValueError("invalid declared control mode/count")
    packets = [tuple(map(int, match)) for match in PACKET.findall(stdout)]
    summary = [tuple(map(int, match)) for match in SUMMARY.findall(stdout)]
    expected_counts = [(count + 3 - cu) // 4 for cu in range(4)]
    if len(packets) != 4 or len(summary) != 1 or summary[0][0] != count:
        raise ValueError("missing or duplicate search controls")
    if [row[0] for row in packets] != expected_counts or \
            any(row[2] != (mode == "stalled") or row[3] != 339 for row in packets):
        raise ValueError("search control scope or FIFO topology differs")
    if sum(row[1] for row in packets) != summary[0][1]:
        raise ValueError("search probe ledger does not close")
    if count and not summary[0][1]:
        raise ValueError("search did no binary work")
    if any((not row[0] and (row[1] or row[4])) or row[5] <= 0 for row in packets) or \
            len({row[5] for row in packets}) != 1:
        raise ValueError("empty-lane work or inconsistent vendor packet width")
    return {"updates": count, "binary_probes": summary[0][1],
            "cu_controls": [{"updates": row[0], "binary_probes": row[1],
                             "blocked_output_writes": row[4], "host_vendor_keep_bits": row[5]}
                            for row in packets],
            "ordered_packets_pass": True, "finite_channels_conserved": True}


def analyze(report, previous):
    expected = {(name, count, mode) for name, count, _ in CASES for mode in MODES}
    actual = [(row["case"], row["updates"], row["mode"]) for row in report["rows"]]
    if len(actual) != len(expected) or set(actual) != expected or report.get("errors") or \
            len(report.get("matrix", [])) != len(expected) or set(map(tuple, report["matrix"])) != expected:
        raise ValueError("incomplete, duplicate or failed finite search declaration")
    if previous.get("status") != "G_METADATA_CREDIT_PREDICTIONS_VALIDATED" or previous.get("errors"):
        raise ValueError("candidate work requires the completed metadata-buffer checkpoint")
    selected = [row for row in previous["rows"]
                if row["arm"] == "cached_hot64_m32" and row["latency"] == 64]
    if len(selected) != len(CASES) or {(row["case"], row["updates"]) for row in selected} != \
            {(name, count) for name, count, _ in CASES}:
        raise ValueError("missing or duplicate candidate work reference")
    observations = {(row["case"], row["updates"]): row["observation"]
                    for row in previous["rows"] if row["arm"] == "cached_hot64_m32" and row["latency"] == 64}
    for row in report["rows"]:
        control = row["control"]
        if control["updates"] != row["updates"] or control["ordered_packets_pass"] is not True or \
                control["finite_channels_conserved"] is not True:
            raise ValueError("finite source control did not pass")
        if control["binary_probes"] != observations[row["case"], row["updates"]]["binary_probes"]:
            raise ValueError("HLS/source work differs from candidate cycle engine")
        execution = row.get("execution", {})
        if execution.get("exit_code") != 0 or execution.get("timed_out") is not False:
            raise ValueError("source control execution failed or timed out")
    for key in ("hardware_timing_admitted", "production_baseline_admitted", "publication_match_admitted"):
        if report.get(key) is not False:
            raise ValueError("finite source tests cannot admit timing or production")
    return {"scope": "19_inputs_x_2_output_modes_x_4_CUs", "executions": len(actual),
            "cu_controls": len(actual) * 4, "work_matches_cycle_engine": True,
            "claim": "bounded_host_execution_of_HLS_stages_not_RTL_or_cycle_calibration"}
