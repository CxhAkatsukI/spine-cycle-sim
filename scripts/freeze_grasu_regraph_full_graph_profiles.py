#!/usr/bin/env python3
"""Freeze simulator-only GraSU + ReGraph full-graph address profiles."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
ARCHITECTURES = ROOT / "configs/architectures"
SOURCE_CATALOG = (
    ROOT / "configs/contracts/grasu_regraph_publication_capabilities_v6.json"
)
TARGET_CATALOG = (
    ROOT / "configs/contracts/grasu_regraph_full_graph_capabilities_v7.json"
)

SOURCE_IDS = (
    "grasu_regraph_candidate10_k1_multipart_weighted_packed_v5",
    "grasu_regraph_candidate10_k1_multipart_pagerank_packed_v5",
    "grasu_regraph_candidate10_k1_multipart_residual_packed_v5",
    "grasu_regraph_candidate10_k1_multipart_cc_packed_v6",
    "grasu_regraph_candidate10_k4_shared_multipart_weighted_packed_v6",
    "grasu_regraph_candidate10_k4_shared_multipart_pagerank_packed_v6",
    "grasu_regraph_candidate10_k4_shared_multipart_residual_packed_v6",
    "grasu_regraph_candidate10_k4_shared_multipart_cc_packed_v6",
)


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def clone(value: Any) -> Any:
    return json.loads(json.dumps(value))


def dump(path: Path, value: object) -> None:
    path.write_text(
        json.dumps(value, indent=2, sort_keys=True) + "\n", encoding="ascii"
    )


def target_id(source_id: str) -> str:
    for suffix in ("_packed_v5", "_packed_v6"):
        if source_id.endswith(suffix):
            return source_id[: -len(suffix)] + "_fullgraph_v7"
    raise ValueError(f"unsupported source profile ID: {source_id}")


def full_graph_profile(source_id: str) -> tuple[Path, dict[str, Any]]:
    source_path = ARCHITECTURES / f"{source_id}.json"
    profile = json.loads(source_path.read_text(encoding="ascii"))
    profile_id = target_id(source_id)
    profile["profile_id"] = profile_id
    profile["status"] = "projected"
    profile["evidence_tier"] = "simulation_only"
    parameters = profile["parameters"]
    parameters.update(
        {
            "grasu_partition_address_layout": "runtime_packed_interleaved_v2",
            "grasu_interleaved_hbm_first_channel": 0,
            "grasu_interleaved_hbm_channels": 23,
            "grasu_interleaved_hbm_bytes": 64,
            "grasu_physical_hbm_channels": 32,
            "hbm_pseudo_channels_budget": 23,
            "physical_address_map_id": "candidate10_hbm_interleaved_arena_v1",
            "regraph_degree_channel": 31,
            "matching_hls_status": (
                "routed_compute_foundation_with_unsynthesized_full_graph_"
                "address_mapper"
            ),
        }
    )
    profile["features"] = list(
        dict.fromkeys(
            [
                *profile["features"],
                "aggregate_23_pseudo_channel_capacity_check",
                "execution_driven_64byte_hbm_interleaving",
                "shared_read_only_row_binary_metadata_crossbar",
                "mapped_physical_channel_arbitration_and_backpressure",
            ]
        )
    )
    profile["limitations"] = [
        (
            "The full-graph address mapper and shared read-only metadata crossbar "
            "are simulator-only; the existing routed HLS compute/update kernels "
            "are the implementation foundation, not a synthesized integrated top."
        ),
        (
            "All unique buffers fail closed against an aggregate budget of 23 x "
            "512 MiB HBM pseudo-channels and are striped at 64-byte granularity."
        ),
        *[
            value
            for value in profile["limitations"]
            if "one 512 MiB pseudo-channel" not in value
            and "exceed physical metadata/PMA capacity" not in value
            and "Runtime-packed buffers fail closed" not in value
        ],
    ]
    return ARCHITECTURES / f"{profile_id}.json", profile


def main() -> int:
    source_catalog = json.loads(SOURCE_CATALOG.read_text(encoding="ascii"))
    source_entries = {
        entry["profile_id"]: entry for entry in source_catalog["profiles"]
    }
    generated: list[tuple[str, Path, dict[str, Any]]] = []
    for source_id in SOURCE_IDS:
        target, profile = full_graph_profile(source_id)
        dump(target, profile)
        generated.append((source_id, target, profile))

    catalog = {
        "schema_version": source_catalog["schema_version"],
        "algorithms": source_catalog["algorithms"],
        "catalog_id": "grasu_regraph_full_graph_capabilities_v7_20260729",
        "profiles": [],
    }
    for source_id, target, profile in generated:
        entry = clone(source_entries[source_id])
        entry["profile_id"] = profile["profile_id"]
        entry["profile_path"] = str(target.relative_to(ROOT))
        entry["profile_sha256"] = sha256(target)
        for capability in entry["supported_algorithms"].values():
            capability["claim_class"] = (
                "simulation_only_full_graph_interleaved_23pc_"
                + str(capability["claim_class"])
            )
            capability["evidence_tier"] = "simulation_only"
        catalog["profiles"].append(entry)
    dump(TARGET_CATALOG, catalog)
    print(f"wrote {len(generated)} profiles and {TARGET_CATALOG}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
