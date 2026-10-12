"""Default-off cross-row model identity; synthesis is not board calibration."""

from pathlib import Path

from spine_cycle_sim.experiments.campaign_runtime import sha256_file
from ..model_contract import BASIS

PROFILE_ID = "grasu_regraph_cross_row_sssp_compute_v1"
TARGET = {
    "reference_adapter_xo_sha256": "752a0395caa5b0117624e6a8055f738e6e608b2272be2d8d118c51b38efa80a2",
    "candidate_adapter_xo_sha256": "7d1785677ca7b54861688d7670d813ca2a4cfdc1e2c83cbc53151cd03ad02b6b",
    "routed": False,
}
SCHEDULE = {"loaded_fifo_capacity": 16, "reader_pipeline_capacity": 74,
            "block_drain_cycles": 74, "publisher_pipeline_cycles": 2,
            "minimum_read_to_use": 71, "segment_issue_interval": 1, "row_advance_cycles": 1}


def expand(root: Path, profile: dict) -> dict:
    from ...sst_candidate import load_profile

    if (set(profile) != {"schema_version", "profile_id", "status", "evidence_tier", "boundary",
                         "basis", "target", "cross_row_schedule", "limitations"}
            or profile.get("schema_version") != 1 or profile.get("profile_id") != PROFILE_ID
            or profile.get("status") != "unrouted_structural_candidate"
            or profile.get("evidence_tier") != "simulator_prediction"
            or profile.get("boundary") != "resident_compute_no_host_launch_gaps"
            or profile.get("basis") != BASIS or profile.get("target") != TARGET
            or profile.get("cross_row_schedule") != SCHEDULE
            or sha256_file(root / BASIS["path"]) != BASIS["sha256"]):
        raise ValueError("unrouted cross-row contract or frozen basis differs")
    basis = load_profile(root, root / BASIS["path"])
    return {**basis, **profile, "architecture": "unrouted_cross_row_on_pinned_dedicated_source_topology",
            "topology_reference": basis["target"],
            "fixed_model": {**basis["fixed_model"], "adapter_empty_segment_exit_cycles": 0,
                            "cross_row_schedule": SCHEDULE}}


def parameters(profile: dict, config: dict) -> dict:
    return {"profile_id": profile["profile_id"], "independent_read_write": 1,
            "routed_stream_depths": 1, "cross_row_model": 1,
            "cross_row_pipeline": int(config["arm"] == "candidate"),
            "row_line_read": 1, "row_prefetch": 1, "stop_after_last": 1}
