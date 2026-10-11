"""Partition coverage and complete-state admission, not hardware speed claims."""

from spine_cycle_sim.experiments.original_regraph_execution.sssp_real_round.analysis import admit_round
from spine_cycle_sim.experiments.original_regraph_execution.sssp_real_round.preparation import read_words

MATRIX = tuple((mode, latency, reverse) for mode, latency in (
    ("cold", 64), ("warm_update", 64), ("warm_update", 128)) for reverse in (0, 1))
STATUS = "passed_four_partition_resident_round_diagnostic_only"


def coverage(layout: dict, capture) -> dict:
    summary = layout["summary"]
    if (not 3 * 65536 < summary["vertices"] <= 258048 or
            (summary["aligned_vertices"], summary["partitions"],
             summary["little"], summary["big"]) != (262144, 4, 4, 0)):
        raise ValueError("study requires four destination partitions and original source lookahead padding")
    degrees = [0] * 4
    for destination in read_words(capture / "csr_destinations.u32le"):
        if not 0 <= destination < 262144:
            raise ValueError("author destination outside four partitions")
        degrees[destination // 65536] += 1
    if not all(degrees) or sum(degrees) != summary["logical_edges"]:
        raise ValueError("missing live destination work in a partition")
    if len(layout["tasks"]) != 16 or any(task["kind"] != "dense" for task in layout["tasks"]):
        raise ValueError("missing original four-by-four dense tasks")
    return {"partitions": 4, "logical_edges_by_destination_partition": degrees,
            "k4_partition_to_worker_from_frozen_controller": [0, 1, 2, 3],
            "independent_runtime_per_worker_counters_available": False}


def admit(stdout, directory, geometry) -> dict:
    row = admit_round(stdout, directory, geometry)
    k4 = row["paths"][1]
    if (geometry["partitions"] != 4 or geometry["padded_vertices"] != 262144
            or k4["extent_reads"] != 4):
        raise ValueError("four-partition execution not complete")
    return row


def matrix(cases: list[dict]) -> dict:
    if [(c["mode"], c["latency"], c["reverse"]) for c in cases] != list(MATRIX):
        raise ValueError("declared four-partition matrix incomplete or reordered")
    for forward, reverse in zip(cases[::2], cases[1::2], strict=True):
        if (forward["paths"] != reverse["paths"]
                or forward["outputs"][0]["sha256"] != reverse["outputs"][0]["sha256"]):
            raise ValueError("registration order changed complete results")
    warm = [case for case in cases if case["mode"] == "warm_update" and not case["reverse"]]
    if warm[0]["outputs"][0]["sha256"] != warm[1]["outputs"][0]["sha256"]:
        raise ValueError("memory latency changed complete warm state")
    for low, high in zip(warm[0]["paths"], warm[1]["paths"], strict=True):
        if high["cycles"] <= low["cycles"] or {k: v for k, v in low.items() if k != "cycles"} != {
                k: v for k, v in high.items() if k != "cycles"}:
            raise ValueError("latency sensitivity or traffic invariance failed")
    return {"status": STATUS, "cases": len(cases), "partitions": 4,
            "complete_state_and_traffic": True, "registration_order_identical": True,
            "warm_latency_sensitivity_checked": True, "convergence_comparison": False,
            "hardware_timing_admitted": False, "publication_match_admitted": False,
            "strict_resource_matched_performance_admitted": False}
