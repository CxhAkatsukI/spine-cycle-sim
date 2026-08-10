"""Architecture-aware grouping of vectorless Vivado hierarchy power."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any, Mapping


class ComponentPowerError(ValueError):
    """Raised when routed hierarchy-power evidence is incomplete."""


_GRASU_UPDATE_PREFIXES = (
    "bin_search_",
    "dispatch_",
    "dispatch_degree_",
    "process_cache_",
    "process_ddr_",
    "grasu_degree_update_",
    "pma_completion_barrier_",
    "pma_to_regraph_adapter_",
)
_GRASU_COMPUTE_PREFIXES = (
    "kernelApply_",
    "kernelHBMWrapper_",
    "kernelLittleGSMerger_",
    "lksg_stream_",
    "pr_source_",
    "regraph_pagerank_apply_",
)
COMPONENT_ORDER = (
    "hbm_subsystem",
    "update_maintenance",
    "graph_compute",
    "stream_fifos",
    "other_user_logic",
)


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _category(system: str, name: str) -> str:
    if name == "hmss_0":
        return "hbm_subsystem"
    if name.startswith("buffer_"):
        return "stream_fifos"
    if system == "spine":
        if name.startswith("spine_partconv_rdmaint_kernel_"):
            return "update_maintenance"
        if name.startswith("spine_partconv_compute_kernel_"):
            return "graph_compute"
    elif system == "grasu_regraph":
        if name.startswith(_GRASU_UPDATE_PREFIXES):
            return "update_maintenance"
        if name.startswith(_GRASU_COMPUTE_PREFIXES):
            return "graph_compute"
    else:
        raise ComponentPowerError(f"unsupported system: {system}")
    return "other_user_logic"


def aggregate_vivado_component_power(
    ledger: Mapping[str, object], *, system: str
) -> dict[str, object]:
    """Aggregate direct ULP children without double counting hierarchy rows."""

    if ledger.get("status") != "PASS":
        raise ComponentPowerError("Vivado power ledger is not PASS")
    summary = ledger.get("summary")
    hierarchy = ledger.get("hierarchy")
    if not isinstance(summary, Mapping) or not isinstance(hierarchy, list):
        raise ComponentPowerError("invalid Vivado power ledger shape")
    if summary.get("confidence_level") != "Low":
        raise ComponentPowerError("unexpected Vivado activity-confidence class")

    ulp_index = next(
        (
            index
            for index, row in enumerate(hierarchy)
            if isinstance(row, Mapping)
            and row.get("name") == "ulp"
            and row.get("indent") == 5
        ),
        None,
    )
    if ulp_index is None:
        raise ComponentPowerError("missing ULP hierarchy root")
    ulp_power = float(hierarchy[ulp_index]["power_w"])
    children: list[Mapping[str, object]] = []
    for row in hierarchy[ulp_index + 1 :]:
        if not isinstance(row, Mapping):
            raise ComponentPowerError("invalid hierarchy row")
        indent = int(row["indent"])
        if indent <= 5:
            break
        if indent == 7:
            children.append(row)
    if not children:
        raise ComponentPowerError("ULP hierarchy has no direct children")

    components = {component: 0.0 for component in COMPONENT_ORDER}
    child_rows = []
    for child in children:
        name = str(child["name"])
        power_w = float(child["power_w"])
        category = _category(system, name)
        components[category] += power_w
        child_rows.append(
            {"name": name, "category": category, "power_w": power_w}
        )
    child_sum = sum(components.values())
    if abs(child_sum - ulp_power) > 0.01:
        raise ComponentPowerError(
            f"ULP child power does not close: children={child_sum}, ulp={ulp_power}"
        )
    dynamic_w = float(summary["dynamic_w"])
    return {
        "system": system,
        "confidence_level": summary["confidence_level"],
        "dynamic_w": dynamic_w,
        "device_static_w": float(summary["device_static_w"]),
        "ulp_power_w": ulp_power,
        "platform_dynamic_residual_w": dynamic_w - ulp_power,
        "components_w": components,
        "ulp_children": child_rows,
    }


def analyze_component_power_manifest(path: str | Path) -> dict[str, Any]:
    """Validate hashes and frozen grouped values for all publication builds."""

    manifest_path = Path(path).resolve()
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    if manifest.get("schema_version") != 1 or manifest.get("claim_class") != (
        "vivado_vectorless_hierarchy_component_attribution_not_workload_energy"
    ):
        raise ComponentPowerError("unsupported component-power manifest")
    root = (manifest_path.parent / manifest["repository_root"]).resolve()
    builds = []
    for entry in manifest.get("builds", []):
        evidence_path = (root / entry["path"]).resolve()
        if _sha256(evidence_path) != entry["sha256"]:
            raise ComponentPowerError(f"{entry['build_id']}: evidence hash mismatch")
        ledger = json.loads(evidence_path.read_text(encoding="utf-8"))
        grouped = aggregate_vivado_component_power(
            ledger, system=entry["system"]
        )
        actual = {
            "dynamic_w": grouped["dynamic_w"],
            "device_static_w": grouped["device_static_w"],
            "ulp_power_w": grouped["ulp_power_w"],
            "components_w": grouped["components_w"],
        }
        if actual != entry["expected"]:
            raise ComponentPowerError(
                f"{entry['build_id']}: grouped values differ from frozen expectation"
            )
        builds.append({**entry, **grouped})
    if len(builds) != 4:
        raise ComponentPowerError("component-power evidence requires four routed builds")
    algorithms = {
        build["algorithm"]
        for build in builds
        if build["system"] == "grasu_regraph"
    }
    if algorithms != {
        "weighted_sssp",
        "full_pagerank",
        "thresholded_residual_pagerank",
    }:
        raise ComponentPowerError("GraSU+ReGraph component power lacks an algorithm")
    return {
        "schema_version": 1,
        "claim_class": manifest["claim_class"],
        "builds": builds,
        "limitations": manifest.get("limitations", []),
        "status": "PASS",
    }
