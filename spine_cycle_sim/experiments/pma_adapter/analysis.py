"""Complete matched-state, physical-work and explicitly modeled-window analysis."""

import json
from pathlib import Path

from spine_cycle_sim.experiments.campaign_runtime import sha256_file
from ..upstream_controls.grasu.analysis import unique_fields

STATUS = "FINITE_A4_B_FUNCTIONAL_PASS_TIMING_PREDICTED"


def union_length(intervals):
    total = end = 0
    for start, stop in sorted(intervals):
        if not 0 <= start <= stop:
            raise ValueError("invalid stage interval")
        total += max(0, stop - max(start, end))
        end = max(end, stop)
    return total


def analyze(stdout: str, stderr: str, directory: Path, case: dict, item: dict, old: dict, contract: dict):
    lines = stdout.splitlines()
    if stderr or any(not line.startswith(("PMA_R_EXECUTION ", "PMA_R_PROGRESS ")) for line in lines):
        raise ValueError("finite PMA unexpected diagnostics")
    rows = [json.loads(line.removeprefix("PMA_R_EXECUTION "), object_pairs_hook=unique_fields)
            for line in lines if line.startswith("PMA_R_EXECUTION ")]
    if len(rows) != 1:
        raise ValueError("finite PMA needs one complete result")
    row = rows[0]
    if (row.get("passed") is not True or row.get("queues_and_requests_conserved") is not True or
            row.get("timing_calibrated_to_FPGA") is not False or
            row.get("kind") != "schedule_informed_finite_PMA_original_A4_iteration"):
        raise ValueError("finite PMA correctness/evidence gate failed")
    excluded = {"passed", "queues_and_requests_conserved", "timing_calibrated_to_FPGA", "kind", "paths", "segment_reads", "publication_finishes", "timing"}
    if any(type(value) is not int or value < 0 for key, value in row.items() if key not in excluded):
        raise ValueError("finite PMA counter must be a nonnegative integer")
    facts = item["source_counts"]
    expected = {"iterations": 1, "argument": 0, "little": 4, "big": 0, "clock_mhz": 210,
        "memory_latency": case["latency"], "state_parent_credits": case["state_parents"], "input_parent_credits": 16,
        "outstanding_bursts": 16, "logical_edges": facts["logical_edges"], "physical_edges": facts["physical_edges"],
        "dummy_edges": facts["dummy_edges"], "row_word_reads": facts["row_word_reads"],
        "row_bus_bytes": facts["row_word_reads"] * 64, "pma_bus_bytes": facts["source_pma_read_bytes"],
        "checked_sum_words": old["result"]["checked_sum_words"], "checked_replica_words": old["result"]["checked_replica_words"],
        "degree_read_bytes": old["result"]["degree_read_bytes"], "property_write_bytes": old["result"]["property_write_bytes"]}
    if any(type(row.get(key)) is not int or row.get(key) != value for key, value in expected.items()):
        raise ValueError("finite PMA work/resource/window scope differs")
    if (type(row.get("timing")) is not dict or row["timing"] != contract["timing"] or
            any(type(value) is not int for value in row["timing"].values())):
        raise ValueError("finite PMA compiled timing differs from declared assumptions")
    required = {"cycles", "read_bytes", "write_bytes", "source_read_bytes", "input_requests", "input_acknowledgements",
                "segment_reads", "paths", "publication_finishes", "input_output_stalls", "overlapped_task_starts", "contended_channel_cycles"}
    if not required.issubset(row) or type(row["segment_reads"]) is not list or len(row["segment_reads"]) != 4 or any(type(v) is not int or v < 0 for v in row["segment_reads"]):
        raise ValueError("finite PMA required counters/windows missing or invalid")
    if (not 0 < row["cycles"] <= contract["max_cycles"] or row["read_bytes"] != row["row_bus_bytes"] + row["pma_bus_bytes"] + row["source_read_bytes"] + row["degree_read_bytes"] or
            row["write_bytes"] != row["property_write_bytes"] or row["source_read_bytes"] % 16384 or
            row["input_requests"] != facts["row_word_reads"] + facts["physical_edges"] // 16 or
            row["input_acknowledgements"] != row["input_requests"] or row["segment_reads"] != facts["pma_segment_reads"]):
        raise ValueError("finite PMA memory/request ledger failed")
    files = []
    for replica in range(4):
        path = directory / f"final_replica{replica}.u32le"
        if path.is_symlink():
            raise ValueError("finite PMA state capture must not be a symlink")
        files.append({"path": path.name, "sha256": sha256_file(path), "bytes": path.stat().st_size})
    if files != old["files"]:
        raise ValueError("finite PMA full state differs from original A4")
    paths = row["paths"]
    if type(paths) is not list or any(type(path) is not dict or type(path.get("kernel")) is not int for path in paths) or [path.get("kernel") for path in paths] != list(range(4)):
        raise ValueError("finite PMA path matrix missing")
    reader_intervals, compute_intervals, overlap = [], [], []
    partitions = item["layout"]["summary"]["partitions"]
    for path in paths:
        fields = [path.get(name) for name in ("starts", "reader_finishes", "compute_starts", "frontend_finishes", "completions")]
        if any(type(values) is not list or len(values) != partitions or any(type(v) is not int or v < 0 for v in values) for values in fields):
            raise ValueError("finite PMA task windows incomplete")
        for start, reader_end, compute, frontend_end, end in zip(*fields, strict=True):
            if not start < reader_end <= end <= row["cycles"] or not start < compute <= frontend_end <= end:
                raise ValueError("finite PMA task windows invalid")
            reader_intervals.append((start, reader_end))
            compute_intervals.append((compute, frontend_end))
            overlap.append((max(start, compute), max(max(start, compute), min(reader_end, frontend_end))))
        if fields[0][0] != 0 or any(start < end for start, end in zip(fields[0][1:], fields[4][:-1], strict=True)):
            raise ValueError("finite PMA task restart precedes drain")
    publications = row["publication_finishes"]
    if (type(publications) is not list or len(publications) != partitions or any(type(v) is not int or not 0 < v <= row["cycles"] for v in publications) or
            publications != sorted(set(publications))):
        raise ValueError("finite PMA publication windows invalid")
    return {"status": STATUS, "result": row, "files": files, "matched_A4_cycles": old["result"]["cycles"],
        "modeled_overhead_pct": (row["cycles"] / old["result"]["cycles"] - 1) * 100,
        "input_read_bytes_ratio": (row["row_bus_bytes"] + row["pma_bus_bytes"]) / old["result"]["edge_read_bytes"],
        "row_logical_read_bytes": row["row_word_reads"] * 8,
        "window_unions_not_additive_stage_costs": {"reader_cycles": union_length(reader_intervals),
            "frontend_cycles": union_length(compute_intervals), "same_path_overlap_cycles": union_length(overlap)},
        "FPGA_measured_cycles": None, "publication_rate_error_pct": None}


def check_matrix(cases):
    admitted = {row["id"]: row["analysis"] for row in cases if row["status"] == STATUS}
    pairs = []
    for name in ("boundary", "skewed", "amazon"):
        if name in admitted and name + "_reverse" in admitted:
            if admitted[name] != admitted[name + "_reverse"]:
                raise ValueError("finite PMA registration order changed full observations")
            pairs.append(name)
    for name in ("boundary_two_parents", "boundary_latency128"):
        if name in admitted and "boundary" in admitted:
            if admitted[name]["files"] != admitted["boundary"]["files"] or admitted[name]["result"]["cycles"] < admitted["boundary"]["result"]["cycles"]:
                raise ValueError("finite PMA resource pressure changed state or reduced latency")
    return {"reverse_pairs_identical": pairs, "unadmitted_cases": [row["id"] for row in cases if row["status"] != STATUS]}
