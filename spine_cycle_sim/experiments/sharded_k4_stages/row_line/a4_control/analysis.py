"""Full-state/traffic and exact historical replay, not calibrated FPGA timing."""

import json
from pathlib import Path

from spine_cycle_sim.experiments.campaign_runtime import sha256_file
from spine_cycle_sim.experiments.original_regraph_validation.analysis import same_typed
from spine_cycle_sim.experiments.original_regraph_execution.sssp_partition_round.analysis import admit as admit_pair
from ...empty_segment.sensitivity.analysis import admit as admit_legacy
from .contract import ARMS, MATRIX, STATUS, run_specs


def output_signatures(outputs):
    return [{**item, "path": Path(item["path"]).name} for item in outputs]


def exact_pair(stdout, state, geometry, frozen):
    admitted = admit_pair(stdout, state, geometry)
    if (not same_typed(admitted["paths"], frozen["paths"])
            or output_signatures(admitted["outputs"]) != output_signatures(frozen["outputs"])):
        raise ValueError("rebuilt original A4/legacy K4 differs from frozen result")
    return admitted


def candidate(stdout, state, geometry, frozen, skip, arm, layout):
    lines = stdout.splitlines()
    metadata = [json.loads(line.removeprefix("MODEL_CONTROL ")) for line in lines
                if line.startswith("MODEL_CONTROL ")]
    empty_exit, row_line = ARMS[arm]
    if not same_typed(metadata, [{"row_line_reads": row_line, "empty_segment_exit_cycles": empty_exit,
                                 "fixed_rounds": 1, "hardware_timing_admitted": False,
                                 "strict_resource_match_admitted": False}]):
        raise ValueError("missing or duplicate model declaration")
    counters = [json.loads(line.removeprefix("REAL_ROUND ")) for line in lines if line.startswith("REAL_ROUND ")]
    if len(counters) != 1:
        raise ValueError("missing or duplicate K4 counters")
    counters = counters[0]
    if any(type(value) is not int or value < 0 for key, value in counters.items()
           if key not in {"path", "passed", "full_state_and_traffic_pass"}):
        raise ValueError("invalid K4 counter")
    expected = dict(skip["counters"])
    if row_line:
        row_reads = sum((row["rows_visited"] + 7) // 8 for row in layout["partitions"])
        expected["read_bytes"] -= (expected["row_reads"] - row_reads) * 64
        expected["row_reads"] = row_reads
        expected["cycles"] = counters["cycles"]
    if not same_typed(expected, counters) or not 0 < counters["cycles"] <= 100000000:
        raise ValueError("K4 legacy cycles or independently expected traffic differs")
    outputs = []
    for item in frozen["outputs"]:
        name = Path(item["path"]).name
        if not name.startswith("k4_"):
            continue
        path = state / name
        if path.is_symlink() or path.stat().st_size != geometry["padded_vertices"] * 4 or sha256_file(path) != item["sha256"]:
            raise ValueError("complete candidate state differs from frozen oracle")
        outputs.append({"path": str(path), "bytes": path.stat().st_size, "sha256": sha256_file(path)})
    invocations = [json.loads(line.removeprefix("INVOCATION ")) for line in lines if line.startswith("INVOCATION ")]
    keys = []
    for row in invocations:
        if (row.keys() != {"round", "partition", "worker", "adapter", "start", "end"}
                or type(row["adapter"]) is not bool
                or any(type(row[key]) is not int for key in row if key != "adapter")
                or row["round"] != 1 or not 0 <= row["partition"] < 4
                or row["worker"] != row["partition"] % 4
                or not 0 <= row["start"] < row["end"] <= counters["cycles"]):
            raise ValueError("invalid partition/worker invocation bounds")
        keys.append((row["partition"], row["adapter"]))
    if sorted(keys) != sorted((p, adapter) for p in range(4) for adapter in (False, True)):
        raise ValueError("missing or duplicate partition execution")
    return {"counters": counters, "outputs": outputs, "invocations": invocations,
            "k4_over_A4_cycles_diagnostic_only": counters["cycles"] / frozen["paths"][0]["cycles"],
            "legacy_over_candidate_cycles_diagnostic_only": frozen["paths"][1]["cycles"] / counters["cycles"]}


def admit(stdout, state, geometry, frozen, skip, arm, layout):
    if arm == "original":
        return exact_pair(stdout, state, geometry, frozen)
    if arm == "legacy_extracted":
        return admit_legacy(stdout, state, geometry, frozen, 73)
    return candidate(stdout, state, geometry, frozen, skip, arm, layout)


def matrix(cases):
    if [(c["mode"], c["latency"], c["reverse"], c["arm"]) for c in cases] != run_specs():
        raise ValueError("predeclared model matrix incomplete or reordered")
    for mode, latency, _ in MATRIX[::2]:
        for arm in ("original", "legacy_extracted", *ARMS):
            pair = [case for case in cases if (case["mode"], case["latency"], case["arm"]) == (mode, latency, arm)]
            left, right = ({k: v for k, v in row.items() if k not in {"mode", "latency", "reverse", "outputs"}}
                           for row in pair)
            if not same_typed(left, right) or output_signatures(pair[0]["outputs"]) != output_signatures(pair[1]["outputs"]):
                raise ValueError("registration order changed complete results")
    for arm in ("skip_empty", "whole_line"):
        low, high = [case for case in cases if case["mode"] == "warm_update" and not case["reverse"] and case["arm"] == arm]
        if (high["counters"]["cycles"] <= low["counters"]["cycles"]
                or {k: v for k, v in high["counters"].items() if k != "cycles"} != {
                    k: v for k, v in low["counters"].items() if k != "cycles"}
                or output_signatures(low["outputs"]) != output_signatures(high["outputs"])):
            raise ValueError("memory sensitivity changed state/work or did not increase cycles")
    return {"status": STATUS, "runs": len(cases), "scenario_keys": len(MATRIX),
            "exact_original_A4_and_legacy_replay": True, "extracted_harness_exact_replay": True,
            "skip_empty_exact_replay": True, "whole_line_full_state_and_expected_traffic": True,
            "registration_order_identical": True, "all_four_workers_executed": True,
            "hardware_timing_admitted": False, "strict_resource_match_admitted": False,
            "publication_match_admitted": False, "convergence_comparison": False}
