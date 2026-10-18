"""Strict selection of the current pairwise-source HLS candidate, without fitting."""

import json
from pathlib import Path

from spine_cycle_sim.experiments.campaign_runtime import sha256_file

PROFILE_ID = "grasu_regraph_bank_stream_sssp_compute_v1"
PROFILE_PATH = "configs/architectures/" + PROFILE_ID + ".json"
PROFILE_SHA256 = "a348355cfd654f5de3475fe292b8b156b8aced3eba15e651dbd5aa77a04642d4"


def expand(root: Path, profile: dict) -> dict:
    from ..sst_candidate import load_profile

    canonical = root / PROFILE_PATH
    if sha256_file(canonical) != PROFILE_SHA256 or profile != json.loads(canonical.read_text()):
        raise ValueError("bank-stream source-bound contract differs")
    basis = profile["timing_basis"]
    if sha256_file(root / basis["path"]) != basis["sha256"]:
        raise ValueError("bank-stream nominal timing basis differs")
    previous = load_profile(root, root / basis["path"])
    # Do not inherit old target/RTL hashes: this is a different physical topology.
    return {**profile, "input_export": previous["input_export"],
            "memory": {**previous["memory"], **profile["memory_overrides"]},
            "fixed_model": {**previous["fixed_model"], "adapter_empty_segment_exit_cycles": 0,
                            "bank_stream_schedule": profile["bank_stream_schedule"]}}


def parameters(config: dict) -> dict:
    if config["arm"] != "candidate":
        raise ValueError("bank-stream profile is candidate-only; original ReGraph needs its own control")
    return {"profile_id": PROFILE_ID, "independent_read_write": 1, "routed_stream_depths": 1,
            "row_line_read": 1, "cross_row_pipeline": 1, "bank_stream_model": 1,
            "row_prefetch": 1, "stop_after_last": 1}


def require_sources(integration: Path, profile: dict) -> list[dict]:
    result = []
    for relative, expected in profile["target"]["hls_sources"].items():
        path = integration / relative
        if sha256_file(path) != expected:
            raise ValueError(f"bank-stream HLS source changed: {relative}")
        result.append({"path": str(path.resolve()), "sha256": expected})
    return result
