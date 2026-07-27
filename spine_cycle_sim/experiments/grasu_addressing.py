"""Physical HBM address contracts for partitioned GraSU + ReGraph runs."""

from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence
from typing import Any


MIB = 1 << 20

FROZEN_CANDIDATE10_ADDRESS_PARAMETERS = {
    "grasu_update_base_bytes": 0,
    "grasu_binary_base_bytes": 64 * MIB,
    "grasu_row_offset_base_bytes": 128 * MIB,
    "grasu_pma_base_bytes": 256 * MIB,
    "grasu_vertex_state_base_bytes": 0,
    "grasu_source_state_base_bytes": 384 * MIB,
    "grasu_source_state_buffer_stride_bytes": 1 * MIB,
    "grasu_degree_base_bytes": 16 * MIB,
    "grasu_partition_address_stride_bytes": 16 * MIB,
}

_ADDRESS_ENVIRONMENT = {
    "GRASU_SST_UPDATE_BASE": "grasu_update_base_bytes",
    "GRASU_SST_BINARY_BASE": "grasu_binary_base_bytes",
    "GRASU_SST_ROW_OFFSET_BASE": "grasu_row_offset_base_bytes",
    "GRASU_SST_PMA_BASE": "grasu_pma_base_bytes",
    "GRASU_SST_VERTEX_STATE_BASE": "grasu_vertex_state_base_bytes",
    "GRASU_SST_SOURCE_STATE_BASE": "grasu_source_state_base_bytes",
    "GRASU_SST_SOURCE_STATE_BUFFER_STRIDE": (
        "grasu_source_state_buffer_stride_bytes"
    ),
    "GRASU_SST_DEGREE_BASE": "grasu_degree_base_bytes",
    "GRASU_SST_PARTITION_ADDRESS_STRIDE": (
        "grasu_partition_address_stride_bytes"
    ),
}


def grasu_hbm_address_environment(parameters: Mapping[str, Any]) -> dict[str, str]:
    """Return the fail-closed SST environment for every physical buffer base."""

    missing = [key for key in _ADDRESS_ENVIRONMENT.values() if key not in parameters]
    if missing:
        raise ValueError(f"GraSU profile is missing physical HBM addresses: {missing}")
    return {
        environment: str(int(parameters[parameter]))
        for environment, parameter in _ADDRESS_ENVIRONMENT.items()
    }


def partition_layout_footprints(
    initial_records: Iterable[Any],
    update_records: Iterable[Any],
    vertices: int,
    partition_vertices: int,
    external_to_internal: Sequence[int],
    *,
    weighted_full_word: bool,
) -> list[dict[str, int]]:
    """Mirror the host PMA reservation enough to bound each partition window."""

    if (
        vertices <= 0
        or partition_vertices <= 0
        or len(external_to_internal) != vertices
    ):
        raise ValueError("invalid partitioned GraSU footprint dimensions")
    partitions = (vertices + partition_vertices - 1) // partition_vertices
    reserved: list[dict[int, set[object]]] = [dict() for _ in range(partitions)]

    def reserve(record: Any) -> None:
        source = int(external_to_internal[int(record.src)])
        destination = int(external_to_internal[int(record.dst)])
        partition = destination // partition_vertices
        local_destination = destination % partition_vertices
        key: object = (
            (local_destination, int(record.weight))
            if weighted_full_word
            else local_destination
        )
        reserved[partition].setdefault(source, set()).add(key)

    for record in initial_records:
        if int(record.diff) != 1:
            raise ValueError("initial GraSU PMA record is not an insertion")
        reserve(record)
    for record in update_records:
        if int(record.diff) > 0:
            reserve(record)

    footprints: list[dict[str, int]] = []
    for partition, rows in enumerate(reserved):
        segments = sum((len(keys) + 15) // 16 for keys in rows.values())
        footprints.append(
            {
                "partition": partition,
                "row_bytes": vertices * 8,
                "binary_bytes": segments * 8,
                "pma_bytes_per_channel": ((segments + 1) // 2) * 64,
                "segments": segments,
            }
        )
    return footprints


def validate_partition_footprints(
    parameters: Mapping[str, Any], footprints: Iterable[Mapping[str, int]]
) -> None:
    stride = int(parameters["grasu_partition_address_stride_bytes"])
    for footprint in footprints:
        for field in ("row_bytes", "binary_bytes", "pma_bytes_per_channel"):
            size = int(footprint[field])
            if size > stride:
                raise ValueError(
                    f"partition {footprint['partition']} {field}={size} exceeds "
                    f"the frozen {stride}-byte address stride"
                )


def validate_grasu_hbm_address_map(
    parameters: Mapping[str, Any],
    channel_bytes: int,
    destination_partitions: int,
    vertices: int,
    physical_updates: int,
) -> dict[str, dict[str, object]]:
    """Validate physical windows after the backend's per-channel address mapping."""

    if min(channel_bytes, destination_partitions, vertices) <= 0 or physical_updates < 0:
        raise ValueError("invalid GraSU physical HBM address-map dimensions")
    maximum_partitions = int(
        parameters["max_destination_partitions_without_address_remap"]
    )
    if destination_partitions > maximum_partitions:
        raise ValueError(
            f"workload needs {destination_partitions} destination partitions; "
            f"the frozen address map supports {maximum_partitions}"
        )

    stride = int(parameters["grasu_partition_address_stride_bytes"])
    pma_first = int(parameters.get("grasu_pma_hbm_first_channel", 0))
    pma_count = int(parameters.get("grasu_pma_hbm_channels", 4))
    pma_channels = tuple(range(pma_first, pma_first + pma_count))
    source_channels = {
        int(parameters["regraph_source_state_channel"]),
        int(parameters["regraph_source_state_mirror_channel"]),
    }
    apply_channel = int(parameters["regraph_apply_state_channel"])
    degree_channel = int(parameters.get("regraph_degree_channel", apply_channel))
    source_stride = int(parameters["grasu_source_state_buffer_stride_bytes"])
    windows: dict[str, dict[str, object]] = {
        "update": {
            "base_bytes": int(parameters["grasu_update_base_bytes"]),
            "size_bytes": ((physical_updates + 3) // 4) * 16,
            "channels": list(pma_channels),
        },
        "binary": {
            "base_bytes": int(parameters["grasu_binary_base_bytes"]),
            "size_bytes": destination_partitions * stride,
            "channels": list(pma_channels),
        },
        "row": {
            "base_bytes": int(parameters["grasu_row_offset_base_bytes"]),
            "size_bytes": destination_partitions * stride,
            "channels": list(pma_channels),
        },
        "pma": {
            "base_bytes": int(parameters["grasu_pma_base_bytes"]),
            "size_bytes": destination_partitions * stride,
            "channels": list(pma_channels),
        },
        "source_state": {
            "base_bytes": int(parameters["grasu_source_state_base_bytes"]),
            "size_bytes": source_stride + vertices * 4,
            "channels": sorted(source_channels),
        },
        "vertex_state": {
            "base_bytes": int(parameters["grasu_vertex_state_base_bytes"]),
            "size_bytes": vertices * 4,
            "channels": [apply_channel],
        },
        "degree": {
            "base_bytes": int(parameters["grasu_degree_base_bytes"]),
            "size_bytes": vertices * 4,
            "channels": [degree_channel],
        },
    }

    for name, window in windows.items():
        base = int(window["base_bytes"])
        size = int(window["size_bytes"])
        end = base + size
        if base < 0 or size < 0 or end > channel_bytes:
            raise ValueError(
                f"{name} physical window [{base}, {end}) exceeds one "
                f"{channel_bytes}-byte HBM pseudo-channel"
            )
        window["end_bytes"] = end

    names = tuple(windows)
    for left_index, left_name in enumerate(names):
        left = windows[left_name]
        left_channels = set(left["channels"])
        for right_name in names[left_index + 1 :]:
            right = windows[right_name]
            if not left_channels.intersection(right["channels"]):
                continue
            overlap = max(int(left["base_bytes"]), int(right["base_bytes"])) < min(
                int(left["end_bytes"]), int(right["end_bytes"])
            )
            if overlap:
                raise ValueError(
                    f"physical HBM windows overlap on a shared channel: "
                    f"{left_name}, {right_name}"
                )
    return windows
