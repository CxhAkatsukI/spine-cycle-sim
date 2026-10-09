"""Admit exact source captures and a complete finite-component test matrix."""

from __future__ import annotations

import json
from pathlib import Path

from spine_cycle_sim.experiments.campaign_runtime import sha256_file
from spine_cycle_sim.experiments.upstream_controls.validation import validate_probe


def same_typed(left, right) -> bool:
    if type(left) is not type(right):
        return False
    if isinstance(left, dict):
        return left.keys() == right.keys() and all(same_typed(left[key], right[key]) for key in left)
    if isinstance(left, list):
        return len(left) == len(right) and all(same_typed(a, b) for a, b in zip(left, right, strict=True))
    return left == right


def admit_captures(directory: Path, root: Path, contract: dict) -> list[dict]:
    report_path = directory / "report.json"
    report = json.loads(report_path.read_text())
    if (report.get("evidence_class") != "upstream_source_functional_only" or
            report.get("all_functional_probes_passed") is not True or
            report.get("device_cycles") is not None):
        raise ValueError("capture requires a passing source-functional control, not timing")
    rows = report.get("probes", [])
    if [row.get("id") for row in rows] != [row["id"] for row in contract["source_controls"]]:
        raise ValueError("capture matrix is missing, duplicated or reordered")
    for item in report["analysis_code"]:
        if sha256_file(root / item["path"]) != item["sha256"]:
            raise ValueError("source-control code identity changed")
    admitted = []
    for row, expected in zip(rows, contract["source_controls"], strict=True):
        probe_expected = {
            "kind": "regraph_little", "passed": True, "source_windows": 2,
            "iterations_per_window": 3, "logical_edges_per_iteration": 257,
            "checked_vertices": expected["checked_words"], "little": expected["little"],
            "big": 0 if expected["little"] == 4 else 3, "physical_edges": 1584,
            "merger_observation": "one_partition_prefix",
        }
        if (row.get("status") != "FUNCTIONAL_PASS_NOT_TIMING" or
                not same_typed(row["observed"], probe_expected) or
                row["run"]["exit_code"] != 0 or row["run"]["timed_out"]):
            raise ValueError("capture has an unadmitted functional boundary")
        validate_probe(Path(row["run"]["stdout"]).read_text(), row["expected"])
        if row["observed"] != row["expected"]:
            raise ValueError("capture observed result differs from expected result")
        for dependency in row["dependencies"]:
            if sha256_file(Path(dependency["path"])) != dependency["sha256"]:
                raise ValueError("source capture dependency changed")
        capture = row["merged_capture"]
        path = Path(capture["path"]).resolve()
        if (not path.is_relative_to(directory.resolve()) or
                capture["format"] != "u32le_source_window_then_iteration_then_vertex" or
                capture["boundary"] != "original_global_little_merger_before_apply" or
                capture["bytes"] != expected["checked_words"] * 4 or
                path.stat().st_size != capture["bytes"] or
                sha256_file(path) != capture["sha256"]):
            raise ValueError("capture hash, extent, representation or boundary mismatch")
        admitted.append({**expected, **capture, "source_report_sha256": sha256_file(report_path)})
    return admitted


def records(stdout: str, prefix: str) -> list[dict]:
    values = [json.loads(line.removeprefix(prefix)) for line in stdout.splitlines()
              if line.startswith(prefix)]
    if not values or any(not isinstance(row, dict) for row in values):
        raise ValueError("missing structured component results")
    for row in values:
        for field in ("cycles", "checked_words", "output_stalls", "capacity_stalls"):
            if type(row.get(field)) is not int or row[field] < 0:
                raise ValueError("component counters must be nonnegative integers")
        if not row["cycles"] or row["checked_words"] != 65536:
            raise ValueError("component result has invalid cycle or partition extent")
    return values


def analyze(invariants: str, comparison: str, repeated: str, contract: dict) -> dict:
    fields = ("clock_mhz", "partition_vertices", "gather_lanes", "default_fifo_depth",
              "uram_write_latency", "forwarding_entries_per_lane", "timing")
    expected_configuration = {field: contract[field] for field in fields}
    for stdout in (invariants, comparison, repeated):
        configurations = [json.loads(line.removeprefix("MODEL_CONFIG "))
                          for line in stdout.splitlines() if line.startswith("MODEL_CONFIG ")]
        if not same_typed(configurations, [expected_configuration]):
            raise ValueError("binary model configuration differs from the declared contract")
    cases = records(invariants, "GATHER_CASE ")
    if [row.get("id") for row in cases] != contract["invariant_cases"]:
        raise ValueError("invariant matrix differs from predeclared cases")
    rows = records(comparison, "SOURCE_COMPARISON ")
    expected = [(control["little"], base, iteration)
                for control in contract["source_controls"] for base in (0, 4096)
                for iteration in range(3)]
    keys = [(row.get("little"), row.get("source_base"), row.get("iteration")) for row in rows]
    if keys != expected or any(type(row.get(field)) is not int for row in rows
                              for field in ("little", "source_base", "iteration")):
        raise ValueError("source-comparison matrix differs from predeclared cases")
    if comparison != repeated:
        raise ValueError("repeated comparison changed output or cycle/stall counters")
    return {
        "status": "FINITE_GATHER_MERGE_FUNCTIONAL_PASS_TIMING_PREDICTED",
        "compared_source_words": sum(row["checked_words"] for row in rows),
        "invariant_cases": cases, "source_comparison": rows,
        "repeat_stdout_and_all_counters_identical": True,
        "observed_configuration": expected_configuration,
        "publication_rate_error_pct": None, "FPGA_cycle_error_pct": None,
    }
