"""Strict, separate SST selection and artifact admission for routed SSSP."""

import json
from pathlib import Path

from spine_cycle_sim.experiments.campaign_runtime import sha256_file

PROFILE_ID = "grasu_regraph_routed_sssp_compute_v1"
INDEPENDENT_PROFILE_ID = "grasu_regraph_routed_sssp_compute_v2"
STREAM_PROFILE_ID = "grasu_regraph_routed_sssp_compute_v3"
STREAM_DEPTHS = {"adapter_stream_depth": 32, "gather_stream_depth": 32, "mux_stream_depth": 32}
FIXED_MODEL = {
    "kernel_mhz": 150, "destination_partition_vertices": 65536, "source_buffer_vertices": 4096,
    "internal_fifo_depth": 8, "external_fifo_depth": 16, "apply_request_window": 16,
    "apply_latency": 100, "apply_capacity": 100, "writeback_latency": 71, "writeback_capacity": 71,
    "adapter_min_read_to_use": 71, "adapter_row_control": 6, "adapter_segment_issue_interval": 2,
    "scatter_latency": 4, "scatter_ii": 1, "scatter_capacity": 5, "max_supersteps": 256,
}


def load_profile(root: Path, path: Path) -> dict:
    profile = json.loads(path.read_text())
    streams = profile.get("profile_id") == STREAM_PROFILE_ID
    independent = profile.get("profile_id") in (INDEPENDENT_PROFILE_ID, STREAM_PROFILE_ID)
    expected_model = {**FIXED_MODEL, **({"independent_read_write": 1} if independent else {}),
                      **(STREAM_DEPTHS if streams else {})}
    if (profile.get("schema_version") != 1 or profile.get("profile_id") not in (PROFILE_ID, INDEPENDENT_PROFILE_ID, STREAM_PROFILE_ID)
            or profile.get("evidence_tier") != "simulator_prediction"
            or profile.get("boundary") != "resident_compute_no_host_launch_gaps"
            or profile.get("fixed_model") != expected_model):
        raise ValueError("profile is not an explicit routed SSSP candidate contract")
    memory = profile["memory"]
    if (memory["backend"] != "direct_dramsim3_transport" or memory["channels"] != 32
            or memory["physical_master_count"] != 9 or memory["axi_outstanding_per_master"] != 16
            or memory["channel_capacity_bytes"] != 512 << 20 or memory["backend_outstanding_per_channel"] != 32
            or sha256_file(root / memory["config"]) != memory["sha256"]):
        raise ValueError("candidate memory contract differs")
    if independent and (memory.get("axi_credit_scope") != "per_read_write_direction"
            or memory.get("backend_response_credit_scope") != "per_read_write_direction"
            or profile["target"].get("wrapper_top_rtl_sha256") != "005f0b40523bd021034c90f179a7d2666001bc1bde1de6af5d6ef0638cc194c7"):
        raise ValueError("independent channels require measured RTL identity and explicit credit scopes")
    if streams:
        from .stream_contract import ROUTED_BD_HASHES
        if profile["target"].get("routed_bd_sha256") != ROUTED_BD_HASHES:
            raise ValueError("stream depths require both routed block-design identities")
    return profile


def require_export_headers(integration: Path, profile: dict) -> list[dict]:
    result = []
    for name, expected in profile["input_export"].items():
        path = integration / "include" / name
        if sha256_file(path) != expected:
            raise ValueError(f"HLS preparation changed: {name}")
        result.append({"path": str(path.resolve()), "sha256": expected})
    return result


def component_parameters(root: Path, config: dict) -> dict:
    profile = load_profile(root, Path(config["profile"]))
    if config["arm"] not in ("original", "candidate") or config["max_cycles"] <= 0:
        raise ValueError("invalid candidate arm or cycle cap")
    optimized = config["arm"] == "candidate"
    result = {"fixture": config["fixture"], "output": config["output"],
            "dram_config": str(root / profile["memory"]["config"]), "dram_output": config["dram_output"],
            "max_cycles": config["max_cycles"], "row_prefetch": int(optimized), "stop_after_last": int(optimized)}
    if profile["profile_id"] in (INDEPENDENT_PROFILE_ID, STREAM_PROFILE_ID):
        result.update(profile_id=profile["profile_id"], independent_read_write=1)
    if profile["profile_id"] == STREAM_PROFILE_ID:
        result["routed_stream_depths"] = 1
    return result
