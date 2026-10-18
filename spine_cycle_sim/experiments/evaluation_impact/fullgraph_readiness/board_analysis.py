"""Check resident convergence results without treating event durations as additive."""

import math

from spine_cycle_sim.experiments.sharded_k4_stages.analysis import analyze_log
from .analysis import fields
from .preparation import PREFIXES

BOUNDARY = "resident_update_to_final_readback_wall_including_host_relaunch"


def single(lines, prefix):
    matches = [fields(line) for line in lines if line.startswith(prefix + " ")]
    if len(matches) != 1:
        raise ValueError("one complete record required: " + prefix)
    return matches[0]


def analyze(row, stdout, stderr, *, bdf):
    if stderr.strip():
        raise ValueError("unexpected board runtime diagnostic")
    lines = stdout.splitlines()
    prefix = PREFIXES[row["algorithm"]]
    initial = single(lines, prefix + "_INPUT")
    result = single(lines, prefix + "_RESULT")
    timing = single(lines, prefix + "_TIMING")
    device = single(lines, "GRASU_REGRAPH_DEVICE")
    repeats = single(lines, "GRASU_SHARDED_UPDATE_REPEAT_CONFIG")
    partitions = (row["vertices"] + 65535) // 65536
    if device != {"bdf": bdf} or repeats.get("repeats") != "1" or \
            repeats.get("restore_pma_between_repeats") != "1":
        raise ValueError("leased board identity or single-update execution differs")
    dimensions = {"vertices": row["vertices"], "logical_updates": row["updates"],
                  "physical_updates": row["updates"], "destination_partitions": partitions}
    if any(int(record[key]) != value for record in (initial, result)
           for key, value in dimensions.items()) or int(initial["static_edges"]) != row["initial_edges"]:
        raise ValueError("board workload dimensions differ from the declared matrix")
    if result.get("status") != "PASS" or result.get("hardware_converged") != "1" or \
            result.get("oracle_converged") != "1" or initial.get("oracle_converged") != "1" or \
            result.get("resident_state") != "old_graph_converged" or \
            result.get("conversion_cost") != "absent" or result.get("k4_frontends") != "4" or \
            result.get("shared_regraph_downstream") != "1":
        raise ValueError("old-converged resident state and hardware/oracle convergence required")
    if row["algorithm"] == "residual_pagerank":
        if any(result.get(key) != "0" for key in ("rank_mismatches", "degree_mismatches")) or \
                result.get("threshold_semantics") != "direct_per_vertex" or \
                not math.isfinite(float(result["max_abs_error"])) or float(result["max_abs_error"]) < 0:
            raise ValueError("residual PageRank oracle or threshold semantics differ")
        slot_key, time_key = "processed_edge_slots_per_execution", "device_e2e_ms"
        if int(result["propagation_rounds"]) < 1:
            raise ValueError("completed residual propagation required")
    else:
        if result.get("mismatches") != "0" or initial.get("resident_state") != "old_graph_converged" or \
                int(result["source_external"]) != row["source"] or \
                int(initial["source_external"]) != row["source"] or int(result["executed_supersteps"]) < 1:
            raise ValueError("source, old-state or exact integer oracle differs")
        slot_key, time_key = "processed_edge_slots_per_superstep", "event_e2e_ms"
    if not 0 < int(initial["pma_slots_total"]) == int(result["pma_slots_total"]) == int(result[slot_key]):
        raise ValueError("full-shard PMA scan conservation failed")
    values = {key: float(value) for key, value in timing.items()}
    if any(not math.isfinite(value) or value < 0 for value in values.values()) or \
            not 0 < values[time_key] <= values["setup_inclusive_ms"] + .001:
        raise ValueError("finite positive event/wall timing with consistent scope required")
    # The host's legacy field name starts after graph/state preload, not before
    # CPU graph preparation. Keep the printed value, but give its boundary a name.
    for line in lines:
        if line.startswith("SHARDED_DEVICE_EVENT ") and set(fields(line)) != {
                "stage", "round", "shard", "worker", "queued_ns", "submit_ns", "start_ns", "end_ns"}:
            raise ValueError("exact device-event fields required")
    traced = analyze_log(stdout, require_trace=True)
    if traced["compute_span_ms"] > values[time_key] + .001:
        raise ValueError("compute timeline exceeds the reported device-event span")
    return {"dataset": row["dataset"], "algorithm": row["algorithm"], "status": "PASS",
            "boundary": BOUNDARY, "resident_wall_ms": values["setup_inclusive_ms"],
            "device_event_span_ms": values[time_key], "input": initial, "result": result,
            "timing_ms": values, "compute_timeline": traced,
            "excluded": ["CPU graph layout and old-state oracle", "FPGA programming",
                         "initial graph/state preload", "result-file serialization"],
            "limits": ["kernel events include stalls and overlap; not exclusive stage counters",
                       "not an original-publication match or Spine speedup by itself"]}
