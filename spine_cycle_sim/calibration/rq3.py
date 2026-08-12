"""Calibration projection for exclusive RQ3 critical-path ledgers."""

from __future__ import annotations

import math
from typing import Mapping


MAINTENANCE_STAGE_KEYS = (
    "t_xfer_cycles",
    "t_reduce_cycles",
    "t_carry_cycles",
    "t_directory_cycles",
    "t_seed_cycles",
    "t_switch_cycles",
)

ITERATIVE_STAGE_KEYS = (
    "t_resolve_cycles",
    "t_app_cycles",
    "t_drain_cycles",
    "t_sync_cycles",
)


def _finite_nonnegative(value: object, name: str) -> float:
    converted = float(value)
    if not math.isfinite(converted) or converted < 0.0:
        raise ValueError(f"{name} must be finite and non-negative")
    return converted


def _project_group(
    row: Mapping[str, object], keys: tuple[str, ...], target: float
) -> dict[str, float]:
    raw = {key: _finite_nonnegative(row.get(key, 0), key) for key in keys}
    raw_total = sum(raw.values())
    if raw_total == 0.0:
        if target != 0.0:
            raise ValueError("nonzero calibrated envelope has no raw stage attribution")
        return {key: 0.0 for key in keys}
    scale = target / raw_total
    return {key: value * scale for key, value in raw.items()}


def project_rq3_stage_ledger(
    row: Mapping[str, object],
    *,
    predicted_maintenance_cycles: float,
    predicted_iterative_span_cycles: float,
) -> dict[str, object]:
    """Project a closed raw ledger into calibrated component envelopes.

    Calibration changes only the maintenance-versus-iteration envelope. The
    exclusive attribution within each envelope remains the execution model's
    direct timestamp-derived fraction. This does not create FPGA per-stage
    counters and callers must retain that evidence boundary.
    """

    truthy = {True, "True", "true", 1, "1"}
    if row.get("ten_stage_supported") not in truthy:
        raise ValueError("RQ3 stage projection requires a supported ten-stage ledger")
    if row.get("ten_stage_ledger_closed") not in truthy:
        raise ValueError("RQ3 stage projection requires a closed ten-stage ledger")
    maintenance = _finite_nonnegative(
        predicted_maintenance_cycles, "predicted_maintenance_cycles"
    )
    iterative = _finite_nonnegative(
        predicted_iterative_span_cycles, "predicted_iterative_span_cycles"
    )
    stage_keys = (*MAINTENANCE_STAGE_KEYS, *ITERATIVE_STAGE_KEYS)
    raw_stages = {
        key: _finite_nonnegative(row.get(key, 0), key) for key in stage_keys
    }
    raw_total = sum(raw_stages.values())
    reported_total = _finite_nonnegative(row.get("total_cycles", 0), "total_cycles")
    if not math.isclose(raw_total, reported_total, rel_tol=0.0, abs_tol=1e-6):
        raise ValueError("raw RQ3 ten-stage ledger does not close to total_cycles")

    calibrated = {
        **_project_group(row, MAINTENANCE_STAGE_KEYS, maintenance),
        **_project_group(row, ITERATIVE_STAGE_KEYS, iterative),
    }
    calibrated_total = maintenance + iterative
    if not math.isclose(
        sum(calibrated.values()), calibrated_total, rel_tol=0.0, abs_tol=1e-6
    ):
        raise ValueError("calibrated RQ3 ten-stage ledger did not close")
    return {
        **{f"raw_{key}": value for key, value in raw_stages.items()},
        **{f"calibrated_{key}": value for key, value in calibrated.items()},
        "raw_total_cycles": raw_total,
        "predicted_maintenance_cycles": maintenance,
        "predicted_iterative_span_cycles": iterative,
        "calibrated_total_cycles": calibrated_total,
        "calibrated_ledger_closed": True,
        "calibration_projection": (
            "v15_component_envelopes_within_group_proportional_"
            "execution_model_attribution"
        ),
        "fpga_per_stage_counters_available": False,
    }
