"""Strict admission of resident-round state/traffic and diagnostic timing only."""

from __future__ import annotations

import json
from pathlib import Path

from spine_cycle_sim.experiments.campaign_runtime import sha256_file

MODES = ("cold", "warm_update", "inactive")
LATENCIES = (64, 128)
REPLICAS = ("a4_replica0", "a4_replica1", "a4_replica2", "a4_replica3",
            "k4_primary", "k4_source0", "k4_source1")


def admit_round(stdout: str, directory: Path, geometry: dict) -> dict:
    rows = [json.loads(line[len("REAL_ROUND "):]) for line in stdout.splitlines()
            if line.startswith("REAL_ROUND ")]
    if [row.get("path") for row in rows] != ["a4", "actual_k4"]:
        raise ValueError("missing, reordered or duplicate compute path")
    padded = geometry["padded_vertices"]
    for row, replicas in zip(rows, (4, 3), strict=True):
        if (row.get("passed") is not True or row.get("full_state_and_traffic_pass") is not True
                or row.get("checked_words_per_replica") != padded or row.get("replicas") != replicas):
            raise ValueError("full-state/traffic gate not passed")
        for key, value in row.items():
            if key not in {"path", "passed", "full_state_and_traffic_pass"}:
                if type(value) is not int or value < 0:
                    raise ValueError("invalid compute counter")
        if not row["cycles"] or not row["read_bytes"] or not row["write_bytes"]:
            raise ValueError("empty compute timing or traffic")
        if row["active_vertices"] > geometry["vertices"]:
            raise ValueError("active count exceeds vertex extent")
        if geometry["mode"] == "inactive" and row["active_vertices"]:
            raise ValueError("inactive control generated active state")
    a4, k4 = rows
    if (a4["active_vertices"] != k4["active_vertices"]
            or a4["physical_edges"] - a4["dummy_edges"] != geometry["logical_edges"]
            or k4["live_edges"] != geometry["logical_edges"]
            or a4["write_bytes"] != padded * 16 or k4["write_bytes"] != padded * 12 + 4):
        raise ValueError("cross-path state/edge/publication conservation failed")
    outputs = []
    for name in REPLICAS:
        path = directory / (name + ".u32le")
        if path.is_symlink() or path.stat().st_size != padded * 4:
            raise ValueError("missing or invalid complete replica")
        outputs.append({"path": str(path), "sha256": sha256_file(path), "bytes": path.stat().st_size})
    if len({item["sha256"] for item in outputs}) != 1:
        raise ValueError("complete A4/K4 replicas differ")
    return {"paths": rows, "outputs": outputs,
            "k4_over_a4_cycles_diagnostic_only": k4["cycles"] / a4["cycles"],
            "hardware_timing_admitted": False, "publication_match_admitted": False}


def admit_matrix(cases: list[dict]) -> dict:
    expected = [(mode, latency, reverse) for mode in MODES for latency in LATENCIES for reverse in (0, 1)]
    if [(c["mode"], c["latency"], c["reverse"]) for c in cases] != expected:
        raise ValueError("resident-round sensitivity matrix is incomplete or reordered")
    for forward, reverse in zip(cases[::2], cases[1::2], strict=True):
        if (forward["paths"] != reverse["paths"]
                or forward["outputs"][0]["sha256"] != reverse["outputs"][0]["sha256"]):
            raise ValueError("registration order changed state, cycles or traffic")
    for mode in MODES:
        rows = [case for case in cases if case["mode"] == mode and not case["reverse"]]
        if rows[0]["outputs"][0]["sha256"] != rows[1]["outputs"][0]["sha256"]:
            raise ValueError("memory service changed numerical results")
        for index in (0, 1):
            low, high = (row["paths"][index] for row in rows)
            if high["cycles"] <= low["cycles"]:
                raise ValueError("higher memory latency did not increase this bounded round")
            if {k: v for k, v in low.items() if k != "cycles"} != {
                    k: v for k, v in high.items() if k != "cycles"}:
                raise ValueError("memory service changed conserved traffic")
    return {"status": "passed_real_topology_resident_round_diagnostic_only", "cases": len(cases),
            "complete_state_and_traffic": True, "registration_order_identical": True,
            "latency_sensitivity_checked": True, "convergence_comparison": False,
            "hardware_timing_admitted": False, "publication_match_admitted": False,
            "strict_resource_matched_performance_admitted": False}
