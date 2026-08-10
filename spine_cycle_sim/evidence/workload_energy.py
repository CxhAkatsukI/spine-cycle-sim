"""Workload-duration energy from routed power and execution-driven activity."""

from __future__ import annotations

from collections import defaultdict
from typing import Any, Mapping, Sequence


class WorkloadEnergyError(ValueError):
    """Raised when a workload energy ledger cannot close."""


POWER_COMPONENTS = (
    "hbm_subsystem",
    "update_maintenance",
    "graph_compute",
    "stream_fifos",
    "other_user_logic",
)


def _number(row: Mapping[str, Any], key: str) -> float:
    value = row.get(key)
    if value in (None, ""):
        return 0.0
    number = float(value)
    if number < 0.0:
        raise WorkloadEnergyError(f"negative {key}")
    return number


def _power_profile(
    rows: Sequence[Mapping[str, Any]], system: str, algorithm: str
) -> tuple[Mapping[str, Any], str]:
    normalized = "grasu_regraph" if system.startswith("grasu_regraph") else system
    exact = [
        row
        for row in rows
        if row["system"] == normalized and row["algorithm"] == algorithm
    ]
    if len(exact) == 1:
        return exact[0], "exact_algorithm_routed_build"
    proxy_algorithm = None
    if normalized == "spine":
        proxy_algorithm = "weighted_sssp"
    elif normalized == "grasu_regraph" and algorithm == "connected_components":
        proxy_algorithm = "weighted_sssp"
    proxy = [
        row
        for row in rows
        if row["system"] == normalized and row["algorithm"] == proxy_algorithm
    ]
    if len(proxy) != 1:
        raise WorkloadEnergyError(
            f"no unique routed power profile for {system}/{algorithm}"
        )
    return proxy[0], f"algorithm_proxy_{proxy_algorithm}"


def _activity_cycles(
    rows: Sequence[Mapping[str, Any]], total_cycles: int
) -> dict[str, int]:
    by_component = {str(row["component"]): row for row in rows}

    def cycles(*names: str) -> int:
        return max(
            (int(_number(by_component[name], "component_cycles")) for name in names if name in by_component),
            default=0,
        )

    hbm = cycles("hbm_frontend")
    update = cycles("maintenance", "update_pma")
    compute = cycles("compute", "compute_pipeline_aggregate")
    if not 0 <= hbm <= total_cycles:
        raise WorkloadEnergyError("HBM activity exceeds the measured E2E window")
    if not 0 <= update <= total_cycles:
        raise WorkloadEnergyError("update activity exceeds the measured E2E window")
    if not 0 <= compute <= total_cycles:
        raise WorkloadEnergyError("compute activity exceeds the measured E2E window")
    return {
        "hbm_subsystem": hbm,
        "update_maintenance": update,
        "graph_compute": compute,
        "stream_fifos": max(update, compute),
        "other_user_logic": total_cycles,
    }


def analyze_workload_energy(
    system_rows: Sequence[Mapping[str, Any]],
    activity_rows: Sequence[Mapping[str, Any]],
    power_rows: Sequence[Mapping[str, Any]],
) -> dict[str, Any]:
    """Build a closed per-component FPGA energy estimate for each execution."""

    activity_by_execution: dict[str, list[Mapping[str, Any]]] = defaultdict(list)
    for row in activity_rows:
        activity_by_execution[str(row["execution_id"])].append(row)

    system_energy: list[dict[str, Any]] = []
    component_energy: list[dict[str, Any]] = []
    for row in system_rows:
        execution_id = str(row["execution_id"])
        total_cycles = int(_number(row, "cycles"))
        clock_mhz = _number(row, "clock_mhz")
        dram_energy_pj = _number(row, "dram_energy_pj")
        if total_cycles <= 0 or clock_mhz <= 0.0 or dram_energy_pj <= 0.0:
            continue
        activity = activity_by_execution.get(execution_id, [])
        if not activity:
            raise WorkloadEnergyError(f"missing component activity: {execution_id}")
        profile, profile_role = _power_profile(
            power_rows, str(row["system"]), str(row["algorithm"])
        )
        component_cycles = _activity_cycles(activity, total_cycles)
        dynamic_uj = 0.0
        for component in POWER_COMPONENTS:
            watts = _number(profile, component)
            active_cycles = component_cycles[component]
            energy_uj = watts * active_cycles / clock_mhz
            dynamic_uj += energy_uj
            component_energy.append(
                {
                    "execution_id": execution_id,
                    "group_id": row["group_id"],
                    "dataset_id": row["dataset_id"],
                    "algorithm": row["algorithm"],
                    "system": row["system"],
                    "component": component,
                    "active_cycles": active_cycles,
                    "power_w": watts,
                    "energy_uj": energy_uj,
                    "power_profile_role": profile_role,
                }
            )
        runtime_us = total_cycles / clock_mhz
        platform_dynamic_uj = _number(profile, "platform_dynamic_residual_w") * runtime_us
        device_static_uj = _number(profile, "device_static_w") * runtime_us
        dram_uj = dram_energy_pj / 1_000_000.0
        total_uj = dynamic_uj + platform_dynamic_uj + device_static_uj + dram_uj
        system_energy.append(
            {
                "execution_id": execution_id,
                "group_id": row["group_id"],
                "dataset_id": row["dataset_id"],
                "algorithm": row["algorithm"],
                "system": row["system"],
                "cycles": total_cycles,
                "clock_mhz": clock_mhz,
                "runtime_us": runtime_us,
                "routed_power_build_id": profile["build_id"],
                "power_profile_role": profile_role,
                "user_logic_dynamic_energy_uj": dynamic_uj,
                "platform_dynamic_energy_uj": platform_dynamic_uj,
                "device_static_energy_uj": device_static_uj,
                "dram_energy_uj": dram_uj,
                "total_estimated_energy_uj": total_uj,
                "energy_ledger_closed": abs(
                    total_uj
                    - (
                        dynamic_uj
                        + platform_dynamic_uj
                        + device_static_uj
                        + dram_uj
                    )
                )
                <= max(1.0e-9, total_uj * 1.0e-12),
            }
        )

    by_group: dict[str, dict[str, Mapping[str, Any]]] = defaultdict(dict)
    for row in system_energy:
        by_group[str(row["group_id"])][str(row["system"])] = row
    pair_energy = []
    for group_id, systems in sorted(by_group.items()):
        spine = systems.get("spine")
        grasu = systems.get("grasu_regraph_k4_shared")
        if spine is None or grasu is None:
            continue
        pair_energy.append(
            {
                "group_id": group_id,
                "dataset_id": spine["dataset_id"],
                "algorithm": spine["algorithm"],
                "spine_total_energy_uj": spine["total_estimated_energy_uj"],
                "grasu_total_energy_uj": grasu["total_estimated_energy_uj"],
                "grasu_to_spine_energy_ratio": grasu["total_estimated_energy_uj"]
                / spine["total_estimated_energy_uj"],
                "spine_power_profile_role": spine["power_profile_role"],
                "grasu_power_profile_role": grasu["power_profile_role"],
            }
        )
    if not pair_energy:
        raise WorkloadEnergyError("no matched Spine/GraSU energy pairs")
    if not all(row["energy_ledger_closed"] for row in system_energy):
        raise WorkloadEnergyError("workload energy ledger did not close")
    return {
        "schema_version": 1,
        "claim_class": (
            "execution_driven_active_cycles_times_vivado_vectorless_power_"
            "plus_dramsim3_energy"
        ),
        "system_rows": system_energy,
        "component_rows": component_energy,
        "pair_rows": pair_energy,
        "limitations": [
            "Vivado routed hierarchy power uses default vectorless activity with Low confidence, not RTL SAIF.",
            "Cycle activity gates component duration but does not reconstruct per-net toggle rates.",
            "Spine non-SSSP and GraSU+ReGraph CC rows use explicitly labeled routed algorithm proxies.",
            "DRAMSim3 supplies HBM-device energy; Vivado hbm_subsystem is retained as FPGA HBM-interface logic.",
            "CACTI selected-SRAM projections remain a separate ASIC ledger and are not mixed into FPGA energy.",
        ],
        "status": "PASS",
    }
