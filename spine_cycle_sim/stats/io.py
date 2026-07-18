"""Read and write simulator result files."""

from __future__ import annotations

import csv
import json
from pathlib import Path
from typing import Any


SUMMARY_FIELDS = [
    "case",
    "workload",
    "vertices",
    "edges",
    "capacity_status",
    "execution_cycles",
    "calibrated_extra_cycles",
    "cycles",
    "calibrated_cycles",
    "simulated_time_ms",
    "edges_per_second",
    "carry_count",
    "maintenance_event_count",
    "maintenance_store_l0_events",
    "maintenance_cascade_events",
    "maintenance_estimated_cycles",
    "maintenance_structural_estimated_cycles",
    "maintenance_calibrated_estimated_cycles",
    "maintenance_scheduled_cycles",
    "maintenance_scan_passes",
    "maintenance_scan_cycles",
    "maintenance_calibrated_scan_cycles",
    "maintenance_max_target_level",
    "hbm_request_count",
    "fifo_stall_cycles",
    "memory_stall_cycles",
    "compute_stall_cycles",
    "sssp_iterations",
    "tiny_active_iterations",
    "hot_enabled",
    "hot_edges",
    "cold_edges",
    "hot_vertex_count",
]


def write_json(path: Path, data: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def write_summary_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=SUMMARY_FIELDS, extrasaction="ignore")
        writer.writeheader()
        for row in rows:
            writer.writerow(row)
