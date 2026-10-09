"""Admit full mixed state/traffic/lifecycles, distinct from publication timing."""

import json
from pathlib import Path

from spine_cycle_sim.experiments.campaign_runtime import sha256_file
from spine_cycle_sim.experiments.original_regraph_validation.analysis import same_typed

STATUS = "MIXED_FULL_GRAPH_PADDED_CONTROL_PASS_TIMING_PREDICTED"


def analyze(text: str, directory: Path, case: dict, admitted: dict, contract: dict) -> dict:
    rows = [json.loads(line.removeprefix("MIXED_EXECUTION ")) for line in text.splitlines() if line.startswith("MIXED_EXECUTION ")]
    if len(rows) != 1 or type(rows[0]) is not dict: raise ValueError("mixed execution needs one structured result")
    row = rows[0]
    if (row.get("kind") != "original_mixed_graph_iteration_padded_control" or row.get("passed") is not True or
            row.get("queues_and_requests_conserved") is not True): raise ValueError("mixed functional gate failed")
    exempt = {"kind", "passed", "queues_and_requests_conserved", "original_host_capacity_pass", "paths"}
    if any(type(value) is not int or value < 0 for key, value in row.items() if key not in exempt):
        raise ValueError("mixed counters must be nonnegative integers")
    shape, source = admitted["geometry"], admitted["layout"]["summary"]
    expected = {**shape, "vertices": source["vertices"], "logical_edges": source["logical_edges"], "iterations": 1,
        "little": 11, "big": 3, "clock_mhz": 210, "argument": 0, "dense": source["dense_partitions"],
        "sparse": source["sparse_groups"], "state_parent_credits": case["state_parents"], "memory_latency": case["latency"],
        "physical_edges": source["task_physical_edges"], "dummy_edges": source["task_dummy_edges"],
        "checked_sum_words": shape["published_vertices"], "checked_replica_words": shape["allocation_vertices"] * 14,
        "edge_read_bytes": source["task_physical_edges"] * 8, "degree_read_bytes": shape["published_vertices"] * 4,
        "write_bytes": shape["published_vertices"] * 4 * 14}
    if not same_typed({key: row.get(key) for key in expected}, expected): raise ValueError("mixed execution differs from declared scope")
    if (not 0 < row.get("cycles", 0) <= contract["max_cycles"] or
            row.get("big_logical_requests") != row.get("big_reads", 0) + row.get("big_cache_hits", 0) or
            row.get("big_source_bytes") != row.get("big_reads", 0) * 64 or row.get("little_source_bytes", 1) % 16384 or
            row.get("read_bytes") != sum(row.get(key, -1) for key in ("edge_read_bytes", "little_source_bytes", "big_source_bytes", "degree_read_bytes"))):
        raise ValueError("mixed finite timing/memory/cache ledger failed")
    paths = row.get("paths")
    if type(paths) is not list or [item.get("kernel") for item in paths] != list(range(14)):
        raise ValueError("mixed path matrix missing/reordered")
    for path in paths:
        starts, ends = path.get("starts"), path.get("completions")
        count = row["dense"] if path["kernel"] < 11 else row["sparse"]
        if (type(starts) is not list or type(ends) is not list or len(starts) != count or len(ends) != count or
                any(type(v) is not int or v < 0 for v in starts + ends) or count and starts[0] != 0 or
                any(start >= end or end > row["cycles"] for start, end in zip(starts, ends, strict=True)) or
                any(start < end for start, end in zip(starts[1:], ends[:-1], strict=True))):
            raise ValueError("mixed path lifecycle invalid")
    files = []
    for replica in range(14):
        path = directory / f"final_replica{replica}.u32le"
        if path.is_symlink() or path.stat().st_size != shape["allocation_vertices"] * 4: raise ValueError("mixed state extent changed")
        files.append({"path": path.name, "bytes": path.stat().st_size, "sha256": sha256_file(path)})
    if len({item["sha256"] for item in files}) != 1: raise ValueError("mixed complete state replicas differ")
    return {"status": STATUS, "result": row, "files": files, "FPGA_cycles": None, "publication_error_pct": None}


def matrix(cases: list[dict]) -> dict:
    rows = {item["id"]: item["runs"][0]["analysis"] for item in cases}
    for name in ("boundary", "skewed", "amazon"):
        if not same_typed(rows[name], rows[name + "_reverse"]): raise ValueError("mixed registration reversal changed result")
    for name in ("boundary_latency128", "boundary_one_parent"):
        if rows[name]["files"] != rows["boundary"]["files"] or rows[name]["result"]["cycles"] <= rows["boundary"]["result"]["cycles"]:
            raise ValueError("mixed pressure must preserve state and increase cycles")
    return {"case_cycles": {key: value["result"]["cycles"] for key, value in rows.items()},
        "reverse_registration_identical": True, "resource_pressure_preserves_state": True,
        "original_host_allocation_status": {key: value["result"]["original_host_capacity_pass"] for key, value in rows.items()}}
