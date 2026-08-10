"""Accounting for persistent, update-only Spine versus GraSU experiments."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping


@dataclass(frozen=True)
class HostRuntimeModel:
    """Explicit host/runtime assumptions shared by both architectures."""

    h2d_gbytes_per_second: float
    launch_sync_microseconds_per_batch: float

    def __post_init__(self) -> None:
        if self.h2d_gbytes_per_second <= 0:
            raise ValueError("H2D bandwidth must be positive")
        if self.launch_sync_microseconds_per_batch < 0:
            raise ValueError("launch/sync overhead cannot be negative")


def _device_seconds(result: Mapping[str, Any]) -> float:
    cycles = int(result["device_cycles"])
    core_mhz = float(result["core_mhz"])
    if cycles < 0 or core_mhz <= 0:
        raise ValueError("invalid device timing")
    return cycles / (core_mhz * 1_000_000.0)


def _validate_result(result: Mapping[str, Any], system: str) -> None:
    if result.get("measurement_window") != "pure_update_only":
        raise ValueError(f"{system} result is not pure update-only")
    if result.get("graph_compute_executed") is not False:
        raise ValueError(f"{system} result executed graph compute")
    if not result.get("resident_state_persistent"):
        raise ValueError(f"{system} result did not preserve resident state")
    if result.get("success") is not True:
        raise ValueError(f"{system} result failed")
    if int(result.get("correctness_mismatches", -1)) != 0:
        raise ValueError(f"{system} result failed correctness")


def _architecture_row(
    *,
    system: str,
    result: Mapping[str, Any],
    host: Mapping[str, Any],
    runtime: HostRuntimeModel,
) -> dict[str, Any]:
    prefix = "spine" if system == "spine" else "grasu"
    updates = int(result["logical_updates"])
    batches = int(result["batch_count"])
    if updates <= 0 or batches <= 0:
        raise ValueError("persistent update result must be non-empty")
    preprocess_seconds = int(host[f"{prefix}_host_preprocess_ns"]) / 1e9
    h2d_bytes = int(host[f"{prefix}_initial_h2d_bytes"]) + int(
        host[f"{prefix}_update_h2d_bytes"]
    )
    h2d_seconds = h2d_bytes / (runtime.h2d_gbytes_per_second * 1e9)
    launch_sync_seconds = (
        batches * runtime.launch_sync_microseconds_per_batch / 1e6
    )
    device_seconds = _device_seconds(result)
    preprocess_plus_device = preprocess_seconds + device_seconds
    modeled_host_inclusive = (
        preprocess_plus_device + h2d_seconds + launch_sync_seconds
    )
    traffic = result.get("backend_traffic", {}).get("combined", {})
    return {
        "system": system,
        "logical_updates": updates,
        "batch_count": batches,
        "device_cycles": int(result["device_cycles"]),
        "core_mhz": float(result["core_mhz"]),
        "device_seconds": device_seconds,
        "host_preprocess_seconds": preprocess_seconds,
        "preprocess_plus_device_seconds": preprocess_plus_device,
        "h2d_bytes": h2d_bytes,
        "modeled_h2d_seconds": h2d_seconds,
        "modeled_launch_sync_seconds": launch_sync_seconds,
        "modeled_host_inclusive_seconds": modeled_host_inclusive,
        "device_updates_per_second": updates / device_seconds,
        "preprocess_plus_device_updates_per_second": updates
        / preprocess_plus_device,
        "modeled_host_inclusive_updates_per_second": updates
        / modeled_host_inclusive,
        "backend_requests": int(traffic.get("requests", 0)),
        "backend_bytes": int(traffic.get("bytes", 0)),
        "correctness_mismatches": 0,
    }


def analyze_persistent_update_pair(
    *,
    dataset_id: str,
    scenario: str,
    host: Mapping[str, Any],
    spine_result: Mapping[str, Any],
    grasu_result: Mapping[str, Any],
    runtime: HostRuntimeModel,
) -> dict[str, Any]:
    """Validate and compare one persistent update trace."""

    _validate_result(spine_result, "Spine")
    _validate_result(grasu_result, "GraSU")
    shape = {
        (
            int(result["logical_updates"]),
            int(result["batch_count"]),
        )
        for result in (spine_result, grasu_result)
    }
    if len(shape) != 1:
        raise ValueError("Spine and GraSU results use different trace shapes")
    updates, batches = shape.pop()
    if int(host["updates"]) != updates or int(host["batch_count"]) != batches:
        raise ValueError("host benchmark and device results use different traces")

    rows = [
        _architecture_row(
            system="spine", result=spine_result, host=host, runtime=runtime
        ),
        _architecture_row(
            system="grasu_regraph",
            result=grasu_result,
            host=host,
            runtime=runtime,
        ),
    ]
    spine, grasu = rows
    return {
        "schema_version": 1,
        "experiment": "persistent_trace_aware_update_only",
        "dataset_id": dataset_id,
        "scenario": scenario,
        "logical_updates": updates,
        "batch_count": batches,
        "correctness": "pass",
        "information_boundary": {
            "spine": "initial_graph_once_then_each_arriving_batch",
            "grasu_regraph": "initial_graph_plus_complete_trace_once",
            "note": "Matches the official trace-aware GraSU PMA reservation boundary.",
        },
        "runtime_model": {
            "h2d_gbytes_per_second": runtime.h2d_gbytes_per_second,
            "launch_sync_microseconds_per_batch": (
                runtime.launch_sync_microseconds_per_batch
            ),
            "claim": "parameterized_not_measured_xrt",
        },
        "rows": rows,
        "spine_speedup": {
            "device_only": grasu["device_seconds"] / spine["device_seconds"],
            "preprocess_plus_device": grasu["preprocess_plus_device_seconds"]
            / spine["preprocess_plus_device_seconds"],
            "modeled_host_inclusive": grasu["modeled_host_inclusive_seconds"]
            / spine["modeled_host_inclusive_seconds"],
        },
    }
