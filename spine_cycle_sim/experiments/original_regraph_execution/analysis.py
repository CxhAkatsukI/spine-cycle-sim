"""Admit complete graph state, finite traversal ledgers and exact repeated timing."""

from __future__ import annotations

import json
from pathlib import Path

from spine_cycle_sim.experiments.campaign_runtime import sha256_file
from spine_cycle_sim.experiments.original_regraph_validation.analysis import same_typed

STATUS = "A4_FULL_GRAPH_FUNCTIONAL_PASS_TIMING_PREDICTED"


def analyze(stdout: str, directory: Path, case: dict, admitted: dict, contract: dict) -> dict:
    rows = [json.loads(line.removeprefix("A4_EXECUTION ")) for line in stdout.splitlines()
            if line.startswith("A4_EXECUTION ")]
    if len(rows) != 1:
        raise ValueError("whole A4 execution needs one complete result")
    row = rows[0]
    if (type(row) is not dict or row.get("passed") is not True or row.get("queues_and_requests_conserved") is not True or
            row.get("kind") != "original_a4_graph_iteration"):
        raise ValueError("whole A4 functional or conservation gate failed")
    if any(type(value) is not int or value < 0 for key, value in row.items()
           if key not in ("passed", "queues_and_requests_conserved", "kind", "paths")):
        raise ValueError("whole A4 counters must be nonnegative integers")
    summary = admitted["layout"]["summary"]
    expected = {"iterations": 1, "little": 4, "big": 0, "argument": 0, "clock_mhz": 210,
        "state_parent_credits": case["state_parents"], "memory_latency": case["latency"], "outstanding_bursts": 16,
        **{key: summary[key] for key in ("vertices", "aligned_vertices", "logical_edges", "partitions")},
        "physical_edges": summary["task_physical_edges"], "dummy_edges": summary["task_dummy_edges"],
        "published_vertices": summary["partitions"] * 65536,
        "checked_sum_words": summary["partitions"] * 65536,
        "checked_replica_words": summary["aligned_vertices"] * 4,
        "edge_read_bytes": summary["task_physical_edges"] * 8,
        "degree_read_bytes": summary["partitions"] * 65536 * 4,
        "property_write_bytes": summary["partitions"] * 65536 * 4 * 4}
    if any(row.get(key) != value for key, value in expected.items()):
        raise ValueError("whole A4 work, resource or state scope differs from its contract")
    required = {"cycles", "source_read_bytes", "read_bytes", "write_bytes", "degree_peak_outstanding",
                "writer_peak_outstanding", "overlapped_task_starts", "paths"}
    if not required.issubset(row):
        raise ValueError("whole A4 is missing required timing, memory or path evidence")
    if (not 0 < row["cycles"] <= contract["max_cycles"] or row["source_read_bytes"] % 16384 or
            row["read_bytes"] != row["edge_read_bytes"] + row["source_read_bytes"] + row["degree_read_bytes"] or
            row["write_bytes"] != row["property_write_bytes"] or
            not 0 < row["degree_peak_outstanding"] <= case["state_parents"] or
            not 0 < row["writer_peak_outstanding"] <= case["state_parents"]):
        raise ValueError("whole A4 cycle or memory/request ledger failed")
    paths = row["paths"]
    if (type(paths) is not list or any(type(path) is not dict for path in paths) or
            [path.get("kernel") for path in paths] != list(range(4))):
        raise ValueError("whole A4 path matrix missing or reordered")
    for path in paths:
        starts, completions = path.get("starts"), path.get("completions")
        if (type(starts) is not list or type(completions) is not list or
                len(starts) != summary["partitions"] or len(completions) != len(starts) or starts[0] != 0 or
                any(type(value) is not int or value < 0 for value in starts + completions) or
                any(start >= end or end > row["cycles"] for start, end in zip(starts, completions, strict=True)) or
                any(start < end for start, end in zip(starts[1:], completions[:-1], strict=True))):
            raise ValueError("whole A4 partition lifecycle is invalid")
    files = []
    for replica in range(4):
        path = directory / f"final_replica{replica}.u32le"
        if path.is_symlink() or path.stat().st_size != summary["aligned_vertices"] * 4:
            raise ValueError("whole A4 state capture extent changed")
        files.append({"path": path.name, "bytes": path.stat().st_size, "sha256": sha256_file(path)})
    if len({item["sha256"] for item in files}) != 1:
        raise ValueError("whole A4 property replicas disagree")
    return {"status": STATUS, "result": row, "files": files, "FPGA_measured_cycles": None,
            "publication_rate_error_pct": None}


def analyze_matrix(cases: list[dict]) -> dict:
    by_id = {case["id"]: case["runs"][0]["analysis"] for case in cases}
    for normal, reverse in (("boundary", "boundary_reverse"), ("skewed", "skewed_reverse"), ("amazon", "amazon_reverse")):
        if not same_typed(by_id[normal], by_id[reverse]):
            raise ValueError("registration order changed whole A4 values, cycles or ledgers")
    for altered in ("boundary_two_parents", "boundary_latency128"):
        if by_id[altered]["files"] != by_id["boundary"]["files"]:
            raise ValueError("resource sensitivity changed whole A4 state")
        if by_id[altered]["result"]["cycles"] <= by_id["boundary"]["result"]["cycles"]:
            raise ValueError("whole A4 timing did not reflect declared resource pressure")
    if by_id["boundary"]["result"]["overlapped_task_starts"] == 0:
        raise ValueError("multiple partitions ran behind an unintended publication barrier")
    return {"reverse_registration_identical": True, "resource_pressure_preserves_state": True,
        "independent_partition_progress_observed": True,
        "case_cycles": {key: value["result"]["cycles"] for key, value in by_id.items()}}
