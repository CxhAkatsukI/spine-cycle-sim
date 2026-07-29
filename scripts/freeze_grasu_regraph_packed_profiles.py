#!/usr/bin/env python3
"""Derive runtime-packed v5 GraSU+ReGraph profiles from frozen v4 profiles."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
ARCHITECTURES = ROOT / "configs/architectures"
CONTRACT = ROOT / "configs/contracts/grasu_regraph_runtime_packed_addressing_v1.json"
CAPABILITIES_V4 = ROOT / "configs/contracts/grasu_regraph_k1_multipart_capabilities_v4.json"
CAPABILITIES_V5 = ROOT / "configs/contracts/grasu_regraph_runtime_packed_capabilities_v5.json"
ALGORITHMS = ("weighted", "pagerank", "residual")
PIPELINES = (1, 2, 4)


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def dump(path: Path, payload: object) -> None:
    path.write_text(
        json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="ascii"
    )


def main() -> int:
    contract_hash = sha256(CONTRACT)
    generated: dict[str, tuple[Path, str]] = {}
    for algorithm in ALGORITHMS:
        for pipelines in PIPELINES:
            source = ARCHITECTURES / (
                f"grasu_regraph_candidate10_k{pipelines}_multipart_{algorithm}_v4.json"
            )
            payload = json.loads(source.read_text(encoding="ascii"))
            old_id = str(payload["profile_id"])
            new_id = old_id.removesuffix("_v4") + "_packed_v5"
            payload["profile_id"] = new_id
            payload["features"] = [
                feature
                for feature in payload["features"]
                if feature != "physical_hbm_pseudo_channel_nonalias_map"
            ] + [
                "runtime_footprint_packed_hbm_buffers",
                "physical_hbm_capacity_checked_nonalias_map",
            ]
            payload["limitations"] = [
                limitation
                for limitation in payload["limitations"]
                if "at most four destination partitions" not in limitation
                and "four destination partitions" not in limitation
            ] + [
                "Runtime packing removes the fixed four-partition address-window artifact but still fails closed when measured buffers exceed one 512 MiB pseudo-channel.",
                "Large datasets that exceed physical metadata/PMA capacity require an explicitly labeled capacity slice or a separately synthesized repartitioning design.",
            ]
            payload["evidence"].append(
                {
                    "kind": "runtime_packed_address_contract",
                    "path": str(CONTRACT.relative_to(ROOT)),
                    "sha256": contract_hash,
                }
            )
            parameters = payload["parameters"]
            parameters.update(
                {
                    "physical_address_map_id": "candidate10_hbm_runtime_packed_v2",
                    "grasu_partition_address_layout": "runtime_packed_v1",
                    "grasu_partition_address_arena_base_bytes": 16 << 20,
                    "grasu_partition_address_alignment_bytes": 4096,
                    "runtime_source_state_stride": True,
                    "matching_hls_status": "routed_worker_with_host_runtime_allocated_partition_buffers",
                }
            )
            parameters.pop("max_destination_partitions_without_address_remap", None)
            target = ARCHITECTURES / f"{new_id}.json"
            dump(target, payload)
            generated[old_id] = (target, sha256(target))

    catalog = json.loads(CAPABILITIES_V4.read_text(encoding="ascii"))
    catalog["catalog_id"] = "grasu_regraph_runtime_packed_capabilities_v5_20260729"
    for profile in catalog["profiles"]:
        old_id = str(profile["profile_id"])
        target, digest = generated[old_id]
        profile["profile_id"] = old_id.removesuffix("_v4") + "_packed_v5"
        profile["profile_path"] = str(target.relative_to(ROOT))
        profile["profile_sha256"] = digest
        for capability in profile["supported_algorithms"].values():
            capability["claim_class"] = str(capability["claim_class"]).replace(
                "multi_partition", "runtime_packed_multi_partition"
            )
    dump(CAPABILITIES_V5, catalog)
    print(f"wrote {len(generated)} profiles and {CAPABILITIES_V5}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
