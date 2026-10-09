"""Validate finite PR state work, repetition, pressure and resident iterations."""

from __future__ import annotations

import json

from .analysis import same_typed

STATUS = "FINITE_PR_STATE_FUNCTIONAL_PASS_TIMING_PREDICTED"


def rows(stdout: str, prefix: str) -> list[dict]:
    result = [json.loads(line.removeprefix(prefix)) for line in stdout.splitlines() if line.startswith(prefix)]
    if not result or any(type(row) is not dict for row in result):
        raise ValueError("missing structured state results")
    return result


def validate_state_rows(stdout: str) -> list[dict]:
    result = rows(stdout, "STATE_CASE ")
    for row in result:
        for key, value in row.items():
            if key not in ("id", "waited_for_write_ack") and (type(value) is not int or value < 0):
                raise ValueError("state counters must be nonnegative integers")
        words, replicas = row["checked_words"], row["replicas"]
        if (not row["cycles"] or words not in (2048, 65536) or replicas not in (4, 14) or
                row["degree_bytes"] != words * 4 or row["degree_requests"] != words // 16 or
                row["write_bytes"] != words * 4 * replicas or
                row["write_requests"] != words // 16 * replicas or
                row["write_acknowledgements"] != row["write_requests"] or
                row["waited_for_write_ack"] is not True or
                not 0 < row["max_apply_live"] <= 100 or not 0 < row["max_writer_live"] <= 72):
            raise ValueError("state bytes, acknowledgement, extent or credit conservation failed")
    return result


def analyze_state(invariants: str, comparison: str, iterations: str,
                  repeated: dict[str, str], contract: dict) -> dict:
    texts = {"state": invariants, "comparison": comparison, "iterations": iterations}
    if not same_typed(texts, repeated):
        raise ValueError("state repeated output/cycles/counters changed")
    for text in texts.values():
        if not same_typed(rows(text, "STATE_CONFIG "), [contract["configuration"]]):
            raise ValueError("state configuration differs from declared model")
    cases = validate_state_rows(invariants)
    if [row["id"] for row in cases] != contract["invariant_cases"]:
        raise ValueError("state invariant matrix changed")
    if any(row["checked_words"] != 2048 or row["replicas"] != 4 or row["case_index"] != 0 for row in cases):
        raise ValueError("state invariant fixture changed")
    if not same_typed(rows(invariants, "STATE_REJECTION "), contract["expected_rejections"]):
        raise ValueError("state protocol rejection matrix changed")
    by_id = {row["id"]: row for row in cases}
    basic = {key: value for key, value in cases[0].items() if key != "id"}
    if any(not same_typed(basic, {key: value for key, value in row.items() if key != "id"})
           for row in cases[1:3]):
        raise ValueError("state reuse or registration-order equivalence failed")
    pressured = by_id["a4_state_one_credit"]
    writer = by_id["a4_state_one_writer_credit"]
    if (pressured["cycles"] <= basic["cycles"] or not pressured["apply_credit_stalls"] or
            pressured["max_apply_live"] != 1 or pressured["max_writer_live"] != 1 or
            writer["cycles"] <= basic["cycles"] or not writer["writer_credit_stalls"] or
            not writer["apply_output_stalls"] or writer["max_writer_live"] != 1 or
            by_id["a4_state_memory128"]["cycles"] <= basic["cycles"]):
        raise ValueError("state resource/memory sensitivity gates failed")
    source_rows = validate_state_rows(comparison)
    keys = [(row["id"], row["replicas"], row["case_index"], row["checked_words"]) for row in source_rows]
    expected = [("source_comparison", control["replicas"], case, 65536)
                for control in contract["source_controls"] for case in range(3)]
    if keys != expected:
        raise ValueError("original Apply comparison matrix changed")
    rounds = rows(iterations, "ITERATION_CASE ")
    if [row.get("id") for row in rounds] != contract["iteration_cases"]:
        raise ValueError("resident iteration matrix changed")
    for row in rounds:
        if not same_typed({key: row[key] for key in contract["iteration_work"]}, contract["iteration_work"]):
            raise ValueError("resident iteration work changed")
        if (type(row["shared_channel_contended_cycles"]) is not int or
                row["shared_channel_contended_cycles"] <= 0 or
                len(row["cycles"]) != 3 or any(type(cycle) is not int or cycle <= 0 for cycle in row["cycles"])):
            raise ValueError("resident iteration cycles or shared-channel contention missing")
    if not same_typed({key: value for key, value in rounds[0].items() if key != "id"},
                      {key: value for key, value in rounds[1].items() if key != "id"}):
        raise ValueError("resident iteration registration-order equivalence failed")
    return {
        "status": STATUS, "invariant_cases": cases, "source_comparison": source_rows,
        "compared_source_words": sum(row["checked_words"] for row in source_rows),
        "resident_iterations": rounds, "observed_configuration": contract["configuration"],
        "repeat_stdout_and_all_counters_identical": True,
        "publication_rate_error_pct": None, "FPGA_cycle_error_pct": None,
    }
