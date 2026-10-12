"""Explicit, unrouted row-line model; never inherit a board identity."""

from pathlib import Path

from spine_cycle_sim.experiments.campaign_runtime import sha256_file

PROFILE_ID = "grasu_regraph_row_line_sssp_compute_v1"
BASIS = {"path": "configs/architectures/grasu_regraph_routed_sssp_compute_v3.json",
         "sha256": "123813ff6db3ea88c2e5b842799da82b1e383f84d90fb97d7c67a5e5c12a8843"}
TARGET = {
    "reference_adapter_xo_sha256": "4bae8791463a71f8b02ccad870d0178b2268cea8cfa6173c480e8a596a24417a",
    "candidate_adapter_xo_sha256": "752a0395caa5b0117624e6a8055f738e6e608b2272be2d8d118c51b38efa80a2",
    "routed": False,
}
SHARED = {"row_prefetch": 1, "stop_after_last": 1, "empty_segment_exit_cycles": 0}
ARMS = {"original": 0, "candidate": 1}


def expand(root: Path, profile: dict) -> dict:
    from ..sst_candidate import load_profile

    if (profile.get("schema_version") != 1 or profile.get("profile_id") != PROFILE_ID
            or profile.get("status") != "unrouted_candidate"
            or profile.get("evidence_tier") != "simulator_prediction"
            or profile.get("boundary") != "resident_compute_no_host_launch_gaps"
            or profile.get("basis") != BASIS or profile.get("target") != TARGET
            or profile.get("shared_adapter_flags") != SHARED or profile.get("arm_row_line_read") != ARMS
            or set(profile) != {"schema_version", "profile_id", "status", "evidence_tier", "boundary",
                                "basis", "target", "shared_adapter_flags", "arm_row_line_read", "limitations"}
            or sha256_file(root / BASIS["path"]) != BASIS["sha256"]):
        raise ValueError("unrouted whole-line contract or frozen basis differs")
    basis = load_profile(root, root / BASIS["path"])
    return {**basis, **profile,
            "architecture": "unrouted_row_line_on_pinned_dedicated_source_topology",
            "topology_reference": basis["target"],
            "fixed_model": {**basis["fixed_model"], "adapter_empty_segment_exit_cycles": 0}}


def parameters(profile: dict, config: dict) -> dict:
    return {"profile_id": profile["profile_id"], "independent_read_write": 1,
            "routed_stream_depths": 1, "row_line_model": 1,
            "row_line_read": ARMS[config["arm"]], "row_prefetch": 1, "stop_after_last": 1}
