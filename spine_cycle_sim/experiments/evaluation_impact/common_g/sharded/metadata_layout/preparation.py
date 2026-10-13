"""Declare replication controls before observing their timing results."""

import json

from spine_cycle_sim.experiments.campaign_runtime import sha256_file
from ...study import ROOT
from ..chronological_contract import contract as chronological_contract
from ..preparation import ARMS as BASE_ARMS, LATENCIES

CONTROLS = ("runtime-row-copies", "runtime-binary-copies", "runtime-both-copies")
ARMS = (*BASE_ARMS, *CONTROLS)
REPLICA_CHANNELS = [3, 9, 15, 20]
STATUS = "METADATA_LAYOUT_DIAGNOSTIC_NOT_BASELINE_ADMISSION"
PREVIOUS = ROOT / ("docs/experiments/comparisons/grasu_regraph_stage_validation/"
                   "evaluation_impact/sharded_batch/chronological_inputs/evidence/matrix.json")


def baseline_value(row):
    return {"case": row["case"], "latency": row["latency"], "arm": row["arm"],
        "observation": {key: value for key, value in row["observation"].items()
                        if key not in ("diagnostics", "resources")},
        "state_sha256": row["state_sha256"]}


def contract(prepared):
    declared = chronological_contract(prepared)
    previous = json.loads(PREVIOUS.read_text())
    def geometry(cases):
        return {name: {key: value for key, value in data.items() if key not in ("graph", "updates")}
                for name, data in cases.items()}
    if (previous["status"] != "CHRONOLOGICAL_G_PREDICTIONS_CHECKED_NOT_BASELINE_ADMISSION" or
            previous["errors"] or geometry(previous["contract"]["cases"]) != geometry(declared["cases"])):
        raise ValueError("complete identical preceding chronological study required")
    declared["matrix"] = [{"case": case, "latency": latency, "arm": arm}
        for latency in LATENCIES for case in declared["cases"] for arm in ARMS]
    declared["baseline_rows"] = [baseline_value(row) for row in previous["rows"]]
    declared["input_pins"].append({"path": str(PREVIOUS), "member": "inputs/previous_matrix.json",
                                  "sha256": sha256_file(PREVIOUS)})
    declared["metadata_diagnostic"] = {
        "replica_channels": REPLICA_CHANNELS,
        "allocation": "four new full immutable buffers; originals retained; common 4KiB-aligned offset beyond all current channel spans",
        "scope": "same one-shard runtime engine; read-only per-cycle observations; no numerical core change",
        "replica_cost": "allocated bytes and channel spans reported; allocation and replication host time excluded",
        "constraint": "within original 23 graph-channel IDs and per-bank capacity; not equal metadata-storage budget",
        "sampling": "overlapping completion markers and port pressure, not additive stage latency"}
    declared["limitations"].extend(["replication controls are not production HLS or a baseline promotion",
        "temporal multi-shard and hot/cold results remain outside this diagnostic"])
    return declared
