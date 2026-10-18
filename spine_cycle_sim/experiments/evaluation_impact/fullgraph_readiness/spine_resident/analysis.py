"""Admit only complete device convergence and the explicit continuous wall window."""

import math
from pathlib import Path

from ..board_analysis import BOUNDARY, single
from ..preparation import ALGORITHMS

PASS = "SPINE_RESIDENT_BOARD_CONVERGENCE_PASS_NOT_BASELINE_OR_STAGE_CALIBRATION"


def analyze(row, stdout, stderr, *, bdf):
    if stderr.strip():
        raise ValueError("unexpected Spine runtime diagnostic")
    lines = stdout.splitlines()
    device = single(lines, "SPINE_DEVICE")
    if device != {"bdf": bdf}:
        raise ValueError("Spine leased board mismatch")
    if row.get("legacy"):
        result = single(lines, "PARTITIONED_ALGORITHM_PASS")
        name = ("thresholded_residual_pagerank" if row["algorithm"] == "residual_pagerank"
                else row["algorithm"])
        expected = {"algorithm": name, "vertices": str(row["vertices"]), "source": str(row["source"]),
                    "case": row["graph"] + ":final", "dynamic_run": "1", "resident_update": "1",
                    "logical_updates": str(row["updates"]), "physical_updates": str(row["updates"]),
                    "coverage": "converged"}
        if any(result.get(key) != value for key, value in expected.items()):
            raise ValueError("retained legacy-path correctness smoke differs")
        return {"status": "PASS", "scope": "legacy_path_correctness_only_not_wall_timing", "result": result}
    result = single(lines, "SPINE_RESIDENT_BENCHMARK_PASS")
    integers = {"algorithm": ALGORITHMS.index(row["algorithm"]), "vertices": row["vertices"],
                "source": row["source"], "logical_updates": row["updates"],
                "physical_updates": row["updates"],
                "host_correction_included": int(row["algorithm"] == "residual_pagerank")}
    if any(int(result[key]) != value for key, value in integers.items()):
        raise ValueError("Spine workload or host-correction scope differs")
    if result["boundary"] != BOUNDARY or result["final_validation"] != "outside_wall" or \
            result["full_state_readback"] != "each_round" or \
            result["case"] != str(Path(row["graph"])) + ":final":
        raise ValueError("resident timing, validation, readback or case contract differs")
    wall = float(result["wall_ms"])
    rounds = int(result["iterations"])
    if not math.isfinite(wall) or wall <= 0 or not 0 <= rounds <= 256:
        raise ValueError("finite wall time and bounded completed propagation required")
    ledgers = [line for line in lines if line.startswith("KERNEL_PAIR_RESULT ")]
    if len(ledgers) != rounds:
        raise ValueError("one accepted device ledger per propagation round required")
    for index, line in enumerate(ledgers):
        ledger = single([line], "KERNEL_PAIR_RESULT")
        if ledger["algorithm"] != "resident_benchmark" or int(ledger["iteration"]) != index or \
                any(int(ledger[key]) for key in ("overflow", "task_error", "source_status", "owner_status")):
            raise ValueError("Spine per-round device ledger failed")
    return {"status": "PASS", "dataset": row["dataset"], "algorithm": row["algorithm"],
            "boundary": BOUNDARY, "resident_wall_ms": wall, "iterations": rounds,
            "result": result, "ledgers": ledgers,
            "limits": ["fixed bitstream, not ten-stage calibration",
                       "full-state readback each round is included",
                       "residual-PR correction/seed remains counted host work",
                       "not publication match or paired speedup by itself"]}
