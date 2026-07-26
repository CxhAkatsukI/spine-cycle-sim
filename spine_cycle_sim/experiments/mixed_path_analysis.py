"""Fail-closed attribution for the Candidate10 mixed fast/full tile case."""

from __future__ import annotations

import csv
import json
from pathlib import Path
from typing import Any


MIXED_CASE = "tiny_mixed_fallback"
MIXED_PATH_CLASS = "mixed_fast_full_no_fallback"


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise ValueError(message)


def _first(values: object, name: str) -> int:
    _require(isinstance(values, list) and bool(values), f"missing {name}")
    return int(values[0])


def load_hardware_case(path: Path, case: str = MIXED_CASE) -> dict[str, str]:
    with path.open(encoding="utf-8", newline="") as stream:
        rows = [row for row in csv.DictReader(stream) if row.get("evidence_case") == case]
    _require(len(rows) == 1, f"expected one hardware row for {case}, found {len(rows)}")
    return rows[0]


def analyze_mixed_path(
    spine: dict[str, Any],
    maintenance: dict[str, Any],
    hardware: dict[str, str],
    *,
    frequency_mhz: float = 150.0,
) -> dict[str, Any]:
    """Validate the schedule and expose scope-separated timing ledgers.

    The simulator intervals are execution-driven core cycles.  The hardware
    values are XRT event durations, so their numerical differences are useful
    diagnostics but are deliberately not treated as calibrated residuals.
    """

    _require(bool(spine.get("success")), "Spine execution did not pass")
    _require(bool(maintenance.get("success")), "maintenance execution did not pass")
    _require(int(spine["input_edges"]) == 8_193, "unexpected mixed input size")
    _require(int(hardware["input_edges"]) == 8_193, "hardware input size mismatch")

    sim_fast = _first(spine.get("fast_tiles_per_round"), "fast tile count")
    sim_full = _first(spine.get("full_tiles_per_round"), "full tile count")
    sim_fallback = _first(
        spine.get("reader_range_fallback_reasons_per_round"),
        "reader fallback reason",
    )
    sim_tasks = _first(spine.get("reader_range_tasks_per_round"), "range task count")
    sim_constructed = _first(
        spine.get("reader_range_construction_payloads_per_round"),
        "construction payload count",
    )
    sim_replayed = _first(
        spine.get("reader_range_replay_payloads_per_round"),
        "replay payload count",
    )
    hardware_schedule = {
        "fast_tiles": int(hardware["fast_path_tiles"]),
        "full_tiles": int(hardware["full_path_tiles"]),
        "fallback_reason": int(hardware["fallback_used"]),
        "range_tasks": int(hardware["task_count"]),
        "construction_payloads": int(hardware["task_construction_payloads"]),
        "replay_payloads": int(hardware["task_replay_payloads"]),
    }
    simulator_schedule = {
        "fast_tiles": sim_fast,
        "full_tiles": sim_full,
        "fallback_reason": sim_fallback,
        "range_tasks": sim_tasks,
        "construction_payloads": sim_constructed,
        "replay_payloads": sim_replayed,
    }
    expected_schedule = {
        "fast_tiles": 1,
        "full_tiles": 1,
        "fallback_reason": 0,
        "range_tasks": 2,
        "construction_payloads": 8_193,
        "replay_payloads": 8_193,
    }
    _require(simulator_schedule == expected_schedule, "simulator mixed schedule mismatch")
    _require(hardware_schedule == expected_schedule, "hardware mixed schedule mismatch")

    launch = int(maintenance["maintenance_launch_to_first_memory_issue_cycles"])
    memory_span = int(maintenance["maintenance_memory_active_span_cycles"])
    drain = int(maintenance["maintenance_post_memory_drain_cycles"])
    maintenance_cycles = int(maintenance["maintenance_cycles"])
    _require(launch + memory_span + drain == maintenance_cycles, "B phase ledger is open")
    _require(bool(maintenance["maintenance_memory_ledger_closed"]), "B request ledger is open")
    _require(bool(maintenance["backend_arbitration"]["ledger_closed"]), "arbiter ledger is open")

    round_cycles = [int(value) for value in spine["round_cycles"]]
    post_maintenance = [int(value) for value in spine["round_post_maintenance_cycles"]]
    _require(len(round_cycles) >= 2 and len(post_maintenance) == len(round_cycles), "round ledger is incomplete")
    dirty_ack_cycles = int(spine["dirty_ack_cycles"])
    known_e2e = sum(round_cycles) + dirty_ack_cycles
    scheduler_boundary = int(spine["cycles"]) - known_e2e
    _require(abs(scheduler_boundary) <= 1, "E2E phase ledger has an unexplained residual")

    hardware_maintenance_cycles = float(hardware["maint_ms"]) * frequency_mhz * 1_000.0
    hardware_compute_event_cycles = float(hardware["conv_ms"]) * frequency_mhz * 1_000.0
    hardware_e2e_event_cycles = float(hardware["kernel_e2e_ms"]) * frequency_mhz * 1_000.0

    return {
        "status": "PASS",
        "case": MIXED_CASE,
        "path_class": MIXED_PATH_CLASS,
        "frequency_mhz": frequency_mhz,
        "schedule_match": True,
        "simulator_schedule": simulator_schedule,
        "hardware_schedule": hardware_schedule,
        "simulator_timing": {
            "scope": "execution_driven_core_cycles",
            "total_cycles": int(spine["cycles"]),
            "maintenance_cycles": maintenance_cycles,
            "maintenance_launch_cycles": launch,
            "maintenance_memory_active_span_cycles": memory_span,
            "maintenance_drain_cycles": drain,
            "first_d_core_span_cycles": post_maintenance[0],
            "termination_round_cycles": sum(round_cycles[1:]),
            "dirty_ack_cycles": dirty_ack_cycles,
            "scheduler_boundary_cycles": scheduler_boundary,
        },
        "hardware_timing": {
            "scope": "xrt_kernel_event_cycles",
            "maintenance_event_cycles": hardware_maintenance_cycles,
            "compute_event_cycles": hardware_compute_event_cycles,
            "e2e_event_cycles": hardware_e2e_event_cycles,
        },
        "diagnostic_differences": {
            "scope_matched": False,
            "maintenance_sim_minus_hw_cycles": maintenance_cycles - hardware_maintenance_cycles,
            "first_d_sim_minus_hw_cycles": post_maintenance[0] - hardware_compute_event_cycles,
            "e2e_sim_minus_hw_cycles": int(spine["cycles"]) - hardware_e2e_event_cycles,
        },
        "attribution": {
            "outer_launch_drain_explains_maintenance_gap": False,
            "shared_channel_contention_observed": bool(
                maintenance["backend_arbitration"]["contended_cycles"]
            ),
            "unresolved_maintenance_gap_location": "active_memory_and_control_interval",
            "hardware_absolute_cycle_calibration_claim": False,
        },
    }


def analyze_files(
    spine_result: Path,
    maintenance_result: Path,
    hardware_csv: Path,
    *,
    frequency_mhz: float = 150.0,
) -> dict[str, Any]:
    spine = json.loads(spine_result.read_text(encoding="utf-8"))
    maintenance = json.loads(maintenance_result.read_text(encoding="utf-8"))
    hardware = load_hardware_case(hardware_csv)
    return analyze_mixed_path(
        spine,
        maintenance,
        hardware,
        frequency_mhz=frequency_mhz,
    )
