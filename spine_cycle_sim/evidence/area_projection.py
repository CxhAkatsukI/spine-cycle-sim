"""Conservative FPGA footprint and SRAM-capacity-equivalent area ledger."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

from .publication_ppa import analyze_publication_ppa_manifest


class AreaProjectionError(ValueError):
    """Raised when an area-projection input is incomplete or drifts."""


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _resolved(root: Path, entry: object, label: str) -> Path:
    if not isinstance(entry, dict) or set(entry) != {"path", "sha256"}:
        raise AreaProjectionError(f"{label} must contain path and sha256")
    path = (root / entry["path"]).resolve()
    if _sha256(path) != entry["sha256"]:
        raise AreaProjectionError(f"{label} SHA256 mismatch")
    return path


def analyze_area_projection_manifest(path: str | Path) -> dict[str, Any]:
    manifest_path = Path(path).resolve()
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    expected_claim = (
        "routed_fpga_footprint_plus_32nm_sram_capacity_equivalent_not_full_asic_area"
    )
    if manifest.get("schema_version") != 1 or manifest.get("claim_class") != expected_claim:
        raise AreaProjectionError("unsupported area-projection manifest")
    root = (manifest_path.parent / manifest["repository_root"]).resolve()
    ppa_path = _resolved(root, manifest.get("ppa_manifest"), "ppa_manifest")
    cacti_path = _resolved(root, manifest.get("cacti_ledger"), "cacti_ledger")
    ppa = analyze_publication_ppa_manifest(ppa_path)
    cacti = json.loads(cacti_path.read_text(encoding="utf-8"))
    if cacti.get("status") != "PASS":
        raise AreaProjectionError("CACTI ledger is not PASS")
    by_id = {
        row["characterization_id"]: row
        for row in cacti.get("characterizations", [])
    }

    calibration = {}
    projections = manifest.get("memory_block_projections", {})
    for resource in ("bram", "uram"):
        spec = projections.get(resource, {})
        block_bytes = spec.get("capacity_bytes_per_block")
        characterization = by_id.get(spec.get("characterization_id"))
        if not isinstance(block_bytes, int) or block_bytes <= 0 or characterization is None:
            raise AreaProjectionError(f"invalid {resource} projection")
        source_bytes = int(characterization["geometry"]["size_bytes"])
        source_area = float(characterization["result"]["area_mm2"])
        calibration[resource] = {
            "capacity_bytes_per_block": block_bytes,
            "characterization_id": characterization["characterization_id"],
            "source_size_bytes": source_bytes,
            "source_area_mm2": source_area,
            "area_mm2_per_byte": source_area / source_bytes,
        }

    rows = []
    for build in ppa["builds"]:
        resources = build["resources"]
        bram_bytes = resources["bram"] * calibration["bram"]["capacity_bytes_per_block"]
        uram_bytes = resources["uram"] * calibration["uram"]["capacity_bytes_per_block"]
        bram_area = bram_bytes * calibration["bram"]["area_mm2_per_byte"]
        uram_area = uram_bytes * calibration["uram"]["area_mm2_per_byte"]
        rows.append(
            {
                "build_id": build["build_id"],
                "system": build["system"],
                "algorithm": build["algorithm"],
                **resources,
                "allocated_bram_bytes": bram_bytes,
                "allocated_uram_bytes": uram_bytes,
                "allocated_onchip_ram_mib": (bram_bytes + uram_bytes) / (1 << 20),
                "projected_32nm_bram_capacity_area_mm2": bram_area,
                "projected_32nm_uram_capacity_area_mm2": uram_area,
                "projected_32nm_sram_capacity_area_mm2": bram_area + uram_area,
                "full_asic_area_available": False,
            }
        )
    return {
        "schema_version": 1,
        "claim_class": expected_claim,
        "calibration": calibration,
        "builds": rows,
        "full_asic_area_available": False,
        "limitations": manifest.get("limitations", []),
        "status": "PASS",
    }
