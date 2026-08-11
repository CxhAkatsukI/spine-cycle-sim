#!/usr/bin/env python3
"""Generate architecture profiles for the routed Spine owner-FIFO xclbins."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
ARCH = ROOT / "configs" / "architectures"
ALIGNMENT_CONTRACT = (
    ROOT / "configs" / "contracts" / "spine_paper_architecture_alignment_v1.json"
)
ALIGNMENT_CONTRACT_SHA256 = (
    "6358e13196d7c65007eb0c49b198ecae5e9935b7feacaa6d0faa78ed41ecc8b2"
)
BUILD_ROOT = Path(
    "/data/feiyang/codex_builds/spine_paper_alignment/owner_fifo_hw_v1"
)

SPECS = {
    "weighted_sssp": {
        "tag": "sssp",
        "revision": "d8c2a2cc7152c839e4739d8d6caa51aecd73a537",
        "xclbin": "spine_partitioned_split_e2e.hw.xclbin",
        "xclbin_sha256": "b6e415f0d749d831a5ee5d98acbd691749cbd13b8a20945b306085f668b69862",
        "timing_sha256": "f07029b54e5384f8a53f258778cbedd519e564c0b67b2f414429d1a519b1f115",
    },
    "connected_components": {
        "tag": "cc",
        "revision": "1a0e03e1b0c3ffcc8b5558ab48cb0aec01d3a548",
        "xclbin": "spine_partitioned_split_e2e.cc.hw.xclbin",
        "xclbin_sha256": "e3d103fcca2c6718ffaacdc6309db9b39047714c53e15c77a087149997f0096b",
        "timing_sha256": "aeef614eae0a98a39c576c8949a6dd6b0e8a7c26c9e9181ed6e708d068eabc29",
    },
    "thresholded_residual_pagerank": {
        "tag": "respr",
        "revision": "1b79b2b73117939464db2cc2902a4d7fd66697e6",
        "xclbin": "spine_partitioned_split_e2e.respr.hw.xclbin",
        "xclbin_sha256": "a8bd5c0b19c5aa57a62f0e0ef630f4359e0823e4c102887f61b233ca2f691c38",
        "timing_sha256": "2f348fa1fe268fc9d0b441664d2f39ea313be4a4087c5cc9e9e91b8044bc1d01",
    },
    "full_pagerank": {
        "tag": "fullpr",
        "revision": "ec6e3b739f35936078e7b3c534dd1c1b63c39786",
        "xclbin": "spine_partitioned_split_e2e.fullpr.hw.xclbin",
        "xclbin_sha256": "67db6906373bdab0cd60561757464793b20d603f24304f6373130ede2c33931a",
        "timing_sha256": "77eed896e1ca1c4c8a3646849bacad33e3f82181d9b2067373ef9a2e6e1d0b78",
    },
}


def dump(payload: dict[str, Any]) -> bytes:
    return (json.dumps(payload, indent=2, sort_keys=True) + "\n").encode("ascii")


def payload(algorithm: str, spec: dict[str, str]) -> dict[str, Any]:
    tag = spec["tag"]
    base = BUILD_ROOT / tag
    algorithm_parameters: dict[str, Any] = {}
    if algorithm == "thresholded_residual_pagerank":
        algorithm_parameters = {
            "pagerank_damping": 0.85,
            "pagerank_epsilon": 1.0e-6,
            "pagerank_residual_contract": "grasu_hardware_warm_dangling_linf",
            "pagerank_residual_max_iterations": 256,
        }
    return {
        "schema_version": 1,
        "profile_id": f"spine_owner_fifo_{tag}_hls_v1",
        "architecture": "spine",
        "status": "stable",
        "evidence_tier": "hardware_validated",
        "source": {
            "repository": "/home/chuxiao/spine-dynamic-graph-reduce-levels",
            "revision": spec["revision"],
            "branch": "codex/paper-owner-fifos",
            "dirty": False,
        },
        "clocks": [
            {"name": "data", "requested_mhz": 150.0, "achieved_mhz": 150.0},
            {"name": "hbm", "requested_mhz": 450.0, "achieved_mhz": 450.0},
        ],
        "memory": {
            "backend": "u55c_hbm",
            "channels": 32,
            "channel_capacity_bytes": 536870912,
            "data_width_bits": 512,
            "max_burst_bytes": 1024,
            "max_outstanding_per_port": 32,
        },
        "parameters": {
            "algorithm_kind": algorithm,
            "comparison_role": "hardware_native_owner_fifo",
            "partitions": 16,
            "hot_shards": 16,
            "cold_families": 16,
            "hot_families": 16,
            "families": 32,
            "levels": 11,
            "level_ratio": 2,
            "vertex_partition_size": 1048576,
            "max_vertices": 16777216,
            "tile_vertices": 65536,
            "split_compute_width": 4,
            "graph_hbm_channels": 16,
            "hbm_pseudo_channels_used": 23,
            "hbm_pseudo_channels_budget": 23,
            "sorted_edges_hbm_channel": 16,
            "vertex_state_hbm_channel": 17,
            "active_bins_hbm_channel": 18,
            "active_out_hbm_channel": 19,
            "metadata_hbm_channel": 20,
            "result_hbm_channel": 21,
            "active_bitmap_hbm_channel": 22,
            "axi_profile": "hls_split_9c08763",
            "maintenance_architecture": (
                "candidate10_refactor31_segmented_exact"
            ),
            "max_sort_edges": 131072,
            "edge_stream_depth": 32,
            "value_stream_depth": 32,
            "command_fifo_depth": 256,
            "range_task_active_gate": 16384,
            "segmented_fallback": True,
            "reader_active_record_control_cycles": 520,
            "segmented_fallback_setup_cycles": 3185887,
            "owner_fifo_depth_per_partition": 256,
            "reactivation_fifo_depth_per_partition": 256,
            "owner_scheduler_enabled": True,
            "device_determines_active_membership": True,
            "host_recomputes_active_membership": False,
            "host_rebin_and_relaunch": True,
            "work_credit_quiescence": True,
            "paper_alignment_contract": "spine_paper_architecture_alignment_v1",
            **algorithm_parameters,
        },
        "features": [
            "routed_owner_fifo_hls",
            "device_queued_in_flight_dirty_state",
            "finite_owner_and_reactivation_fifos",
            "no_lost_reactivation",
            "work_credit_quiescence",
            "device_active_generation",
            "split_readmaintenance_compute",
            "resident_graph_and_algorithm_state",
            "host_rebin_and_relaunch_without_membership_recomputation",
            "dual_oracle_correctness_gate",
        ],
        "evidence": [
            {
                "kind": "paper_alignment_contract",
                "path": str(ALIGNMENT_CONTRACT.relative_to(ROOT)),
                "sha256": ALIGNMENT_CONTRACT_SHA256,
            },
            {
                "kind": "routed_xclbin",
                "path": str(base / "xclbin" / spec["xclbin"]),
                "sha256": spec["xclbin_sha256"],
            },
            {
                "kind": "routed_timing_summary",
                "path": str(
                    base
                    / "reports"
                    / "link"
                    / "imp"
                    / "impl_1_hw_bb_locked_timing_summary_postroute_physopted.rpt"
                ),
                "sha256": spec["timing_sha256"],
            },
        ],
        "limitations": [
            "The host rebins device-produced active IDs and relaunches rounds; host orchestration is outside the frozen device-cycle window.",
            "The routed xclbin anchors implementation identity, but simulator timing claims require separate calibration and immutable holdout evidence.",
            "Per-stage simulator attribution is not a routed per-stage hardware counter and must be labeled as calibrated model attribution.",
        ],
    }


def emit(path: Path, content: bytes, *, check: bool) -> None:
    if check:
        if not path.is_file() or path.read_bytes() != content:
            raise SystemExit(f"stale generated artifact: {path.relative_to(ROOT)}")
        return
    path.write_bytes(content)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()
    for algorithm, spec in SPECS.items():
        path = ARCH / f"spine_owner_fifo_{spec['tag']}_hls_v1.json"
        emit(path, dump(payload(algorithm, spec)), check=args.check)


if __name__ == "__main__":
    main()
