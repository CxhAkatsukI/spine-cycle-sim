"""Physical HBM address contracts for partitioned GraSU + ReGraph runs."""

from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence
from typing import Any


MIB = 1 << 20
INTERLEAVED_LAYOUT = "runtime_packed_interleaved_v2"
SOURCE_STATE_STREAM_BYTES_PER_VERTEX = 4

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


def _align_up(value: int, alignment: int) -> int:
    if value < 0 or alignment <= 0:
        raise ValueError("invalid packed-address alignment")
    return ((value + alignment - 1) // alignment) * alignment


def uses_packed_partition_addresses(parameters: Mapping[str, Any]) -> bool:
    return str(
        parameters.get("grasu_partition_address_layout", "fixed_stride_v1")
    ) in {"runtime_packed_v1", INTERLEAVED_LAYOUT}


def uses_interleaved_hbm_arena(parameters: Mapping[str, Any]) -> bool:
    return (
        str(parameters.get("grasu_partition_address_layout", "fixed_stride_v1"))
        == INTERLEAVED_LAYOUT
    )


def source_state_bytes_per_vertex(parameters: Mapping[str, Any]) -> int:
    """Return the external source-state width used by the algorithm policy."""

    value = int(
        parameters.get(
            "regraph_state_bytes_per_vertex",
            parameters.get("pagerank_state_bytes_per_vertex", 4),
        )
    )
    if value <= 0:
        raise ValueError("source-state bytes per vertex must be positive")
    return value


def required_source_state_stride_bytes(
    parameters: Mapping[str, Any], destination_partitions: int
) -> int:
    """Return the 4 KiB-aligned capacity required by one ping-pong buffer."""

    if destination_partitions <= 0:
        raise ValueError("destination partition count must be positive")
    partition_vertices = int(parameters["regraph_partition_vertices"])
    if partition_vertices <= 0:
        raise ValueError("partition vertex span must be positive")
    required = (
        destination_partitions
        * partition_vertices
        * source_state_bytes_per_vertex(parameters)
    )
    return ((required + 4095) // 4096) * 4096


def source_state_prefetch_guard_bytes(parameters: Mapping[str, Any]) -> int:
    """Return storage for ReGraph's one-window-ahead source prefetch.

    The HLS little-GS scatter requests ``pp_read_round + 1`` while its current
    source window is in flight.  A graph whose padded vertex count is exactly a
    source-window multiple therefore issues one final speculative 32-bit
    window after the second ping-pong buffer.  The request is part of measured
    memory traffic even though its payload is not consumed.
    """

    vertices = int(parameters["regraph_source_buffer_vertices"])
    if vertices <= 0:
        raise ValueError("source-buffer vertices must be positive")
    return _align_up(vertices * SOURCE_STATE_STREAM_BYTES_PER_VERTEX, 64)


def interleaved_row_storage_lower_bound_bytes(
    parameters: Mapping[str, Any], vertices: int
) -> int:
    """Return a topology-independent lower bound for packed row storage."""

    if vertices <= 0:
        raise ValueError("graph vertices must be positive")
    if not uses_interleaved_hbm_arena(parameters):
        raise ValueError("row-storage lower bound requires interleaved HBM")
    partition_vertices = int(parameters["regraph_partition_vertices"])
    alignment = int(parameters["grasu_partition_address_alignment_bytes"])
    if partition_vertices <= 0 or alignment <= 0:
        raise ValueError("invalid packed row-storage geometry")
    partitions = (vertices + partition_vertices - 1) // partition_vertices
    return partitions * _align_up(vertices * 8, alignment)


def interleaved_hbm_capacity_bytes(
    parameters: Mapping[str, Any], channel_capacity_bytes: int
) -> int:
    if channel_capacity_bytes <= 0 or not uses_interleaved_hbm_arena(parameters):
        raise ValueError("invalid interleaved HBM capacity geometry")
    channels = int(parameters["grasu_interleaved_hbm_channels"])
    budget = int(parameters.get("hbm_pseudo_channels_budget", channels))
    if channels <= 0 or channels > budget:
        raise ValueError("invalid interleaved HBM channel budget")
    return channels * channel_capacity_bytes


def grasu_hbm_address_environment(
    parameters: Mapping[str, Any],
    address_regions: Mapping[str, Mapping[str, object]] | None = None,
) -> dict[str, str]:
    """Return the fail-closed SST environment for every physical buffer base."""

    missing = [key for key in _ADDRESS_ENVIRONMENT.values() if key not in parameters]
    if missing:
        raise ValueError(f"GraSU profile is missing physical HBM addresses: {missing}")
    environment = {
        environment: str(int(parameters[parameter]))
        for environment, parameter in _ADDRESS_ENVIRONMENT.items()
    }
    if uses_packed_partition_addresses(parameters):
        environment.update(
            {
                "GRASU_SST_PACKED_PARTITION_ADDRESSES": "1",
                "GRASU_SST_PARTITION_ADDRESS_ARENA_BASE": str(
                    int(parameters["grasu_partition_address_arena_base_bytes"])
                ),
                "GRASU_SST_PARTITION_ADDRESS_ALIGNMENT": str(
                    int(parameters["grasu_partition_address_alignment_bytes"])
                ),
            }
        )
    if uses_interleaved_hbm_arena(parameters):
        if address_regions is None or "_interleaved_arena" not in address_regions:
            raise ValueError(
                "interleaved GraSU addresses require validated address regions"
            )
        arena = address_regions["_interleaved_arena"]
        raw_mappings = arena.get("mappings")
        if not isinstance(raw_mappings, list) or not raw_mappings:
            raise ValueError("interleaved GraSU address map has no mappings")
        mappings: list[str] = []
        for raw in raw_mappings:
            if not isinstance(raw, Mapping):
                raise ValueError("invalid interleaved GraSU address mapping")
            mappings.append(
                ":".join(
                    str(int(raw[field]))
                    for field in (
                        "logical_channel",
                        "logical_begin_bytes",
                        "logical_end_bytes",
                        "global_begin_bytes",
                    )
                )
            )
        environment.update(
            {
                "GRASU_SST_HBM_ADDRESS_MAPPING": "interleaved_arena_v1",
                "GRASU_SST_HBM_ADDRESS_MAPPING_TABLE": ";".join(mappings),
                "GRASU_SST_HBM_INTERLEAVE_FIRST_CHANNEL": str(
                    int(arena["first_channel"])
                ),
                "GRASU_SST_HBM_INTERLEAVE_CHANNELS": str(
                    int(arena["channel_count"])
                ),
                "GRASU_SST_HBM_INTERLEAVE_BYTES": str(
                    int(arena["interleave_bytes"])
                ),
            }
        )
    return environment


def _attach_interleaved_arena(
    parameters: Mapping[str, Any],
    windows: dict[str, dict[str, object]],
    channel_bytes: int,
) -> None:
    first_channel = int(parameters["grasu_interleaved_hbm_first_channel"])
    channel_count = int(parameters["grasu_interleaved_hbm_channels"])
    interleave_bytes = int(parameters.get("grasu_interleaved_hbm_bytes", 64))
    alignment = int(parameters["grasu_partition_address_alignment_bytes"])
    physical_channels = int(parameters.get("grasu_physical_hbm_channels", 32))
    budget = int(parameters.get("hbm_pseudo_channels_budget", channel_count))
    if (
        first_channel < 0
        or channel_count <= 0
        or channel_count > budget
        or first_channel + channel_count > physical_channels
        or interleave_bytes <= 0
        or interleave_bytes & (interleave_bytes - 1)
    ):
        raise ValueError("invalid GraSU interleaved HBM geometry")

    cursor = 0
    mappings: list[dict[str, object]] = []

    def allocate(name: str, channels: Sequence[int], *, shared: bool) -> None:
        nonlocal cursor
        window = windows[name]
        logical_begin = int(window["base_bytes"])
        size = int(window["size_bytes"])
        if size == 0:
            return
        if shared:
            cursor = _align_up(cursor, alignment)
            global_begin = cursor
            cursor += _align_up(size, alignment)
            allocations = [(channel, global_begin) for channel in channels]
        else:
            allocations = []
            for channel in channels:
                cursor = _align_up(cursor, alignment)
                allocations.append((channel, cursor))
                cursor += _align_up(size, alignment)
        for channel, global_begin in allocations:
            mappings.append(
                {
                    "region": name,
                    "logical_channel": channel,
                    "logical_begin_bytes": logical_begin,
                    "logical_end_bytes": logical_begin + size,
                    "global_begin_bytes": global_begin,
                    "shared_read_only_alias": shared,
                }
            )

    # Row bounds and binary-search heads are initialized identically on the
    # four logical GraSU ports and are read-only. The interleaved extension
    # exposes one coherent physical copy through a contended read crossbar.
    allocate("update", tuple(int(value) for value in windows["update"]["channels"]), shared=False)
    allocate("binary", tuple(int(value) for value in windows["binary"]["channels"]), shared=True)
    allocate("row", tuple(int(value) for value in windows["row"]["channels"]), shared=True)
    allocate("pma", tuple(int(value) for value in windows["pma"]["channels"]), shared=False)
    allocate(
        "source_state",
        tuple(int(value) for value in windows["source_state"]["channels"]),
        shared=False,
    )
    allocate(
        "vertex_state",
        tuple(int(value) for value in windows["vertex_state"]["channels"]),
        shared=False,
    )
    allocate("degree", tuple(int(value) for value in windows["degree"]["channels"]), shared=False)

    arena_bytes = _align_up(cursor, interleave_bytes)
    capacity_bytes = channel_count * channel_bytes
    if arena_bytes > capacity_bytes:
        raise ValueError(
            "GraSU interleaved physical arena exceeds the frozen HBM budget: "
            f"{arena_bytes} > {capacity_bytes} bytes "
            f"({channel_count} x {channel_bytes})"
        )
    maximum_local_end = (
        ((arena_bytes + interleave_bytes - 1) // interleave_bytes
         + channel_count - 1)
        // channel_count
    ) * interleave_bytes
    if maximum_local_end > channel_bytes:
        raise ValueError("GraSU interleaved address map exceeds a physical channel")
    windows["_interleaved_arena"] = {
        "address_mapping": "interleaved_arena_v1",
        "first_channel": first_channel,
        "channel_count": channel_count,
        "interleave_bytes": interleave_bytes,
        "arena_bytes": arena_bytes,
        "capacity_bytes": capacity_bytes,
        "maximum_local_end_bytes": maximum_local_end,
        "mappings": mappings,
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
    if uses_packed_partition_addresses(parameters):
        for footprint in footprints:
            for field in ("row_bytes", "binary_bytes", "pma_bytes_per_channel"):
                if int(footprint[field]) < 0:
                    raise ValueError("negative GraSU partition footprint")
        return
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
    footprints: Iterable[Mapping[str, int]] | None = None,
) -> dict[str, dict[str, object]]:
    """Validate physical windows after the backend's per-channel address mapping."""

    if min(channel_bytes, destination_partitions, vertices) <= 0 or physical_updates < 0:
        raise ValueError("invalid GraSU physical HBM address-map dimensions")
    packed = uses_packed_partition_addresses(parameters)
    interleaved = uses_interleaved_hbm_arena(parameters)
    footprint_rows = list(footprints or ())
    if packed:
        if len(footprint_rows) != destination_partitions:
            raise ValueError(
                "runtime-packed address validation requires one footprint per "
                "destination partition"
            )
    else:
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
    required_source_state_bytes = required_source_state_stride_bytes(
        parameters, destination_partitions
    )
    source_prefetch_guard_bytes = source_state_prefetch_guard_bytes(parameters)
    padded_vertices = (
        destination_partitions * int(parameters["regraph_partition_vertices"])
    )
    if packed:
        source_stride = max(source_stride, required_source_state_bytes)
    elif source_stride < required_source_state_bytes:
        raise ValueError(
            "source-state double-buffer stride is too small: "
            f"{source_stride} < {required_source_state_bytes}"
        )
    if packed:
        alignment = int(parameters["grasu_partition_address_alignment_bytes"])
        cursor = _align_up(
            int(parameters["grasu_partition_address_arena_base_bytes"]), alignment
        )

        def pack(field: str) -> tuple[list[int], list[int], int, int]:
            nonlocal cursor
            begin = cursor
            bases: list[int] = []
            sizes: list[int] = []
            for footprint in footprint_rows:
                cursor = _align_up(cursor, alignment)
                size = int(footprint[field])
                bases.append(cursor)
                sizes.append(size)
                cursor += _align_up(size, alignment)
            return bases, sizes, begin, cursor

        binary_bases, binary_sizes, binary_base, binary_end = pack("binary_bytes")
        row_bases, row_sizes, row_base, row_end = pack("row_bytes")
        pma_bases, pma_sizes, pma_base, pma_end = pack("pma_bytes_per_channel")
        source_base = _align_up(cursor, alignment)
        packed_regions = {
            "binary": (binary_base, binary_end, binary_bases, binary_sizes),
            "row": (row_base, row_end, row_bases, row_sizes),
            "pma": (pma_base, pma_end, pma_bases, pma_sizes),
        }
    else:
        source_base = int(parameters["grasu_source_state_base_bytes"])
        packed_regions = {}

    windows: dict[str, dict[str, object]] = {
        "update": {
            "base_bytes": int(parameters["grasu_update_base_bytes"]),
            "size_bytes": ((physical_updates + 3) // 4) * 16,
            "channels": list(pma_channels),
        },
        "binary": {
            "base_bytes": (
                packed_regions["binary"][0]
                if packed
                else int(parameters["grasu_binary_base_bytes"])
            ),
            "size_bytes": (
                packed_regions["binary"][1] - packed_regions["binary"][0]
                if packed
                else destination_partitions * stride
            ),
            "channels": list(pma_channels),
        },
        "row": {
            "base_bytes": (
                packed_regions["row"][0]
                if packed
                else int(parameters["grasu_row_offset_base_bytes"])
            ),
            "size_bytes": (
                packed_regions["row"][1] - packed_regions["row"][0]
                if packed
                else destination_partitions * stride
            ),
            "channels": list(pma_channels),
        },
        "pma": {
            "base_bytes": (
                packed_regions["pma"][0]
                if packed
                else int(parameters["grasu_pma_base_bytes"])
            ),
            "size_bytes": (
                packed_regions["pma"][1] - packed_regions["pma"][0]
                if packed
                else destination_partitions * stride
            ),
            "channels": list(pma_channels),
        },
        "source_state": {
            "base_bytes": source_base,
            "size_bytes": (
                source_stride
                + required_source_state_bytes
                + source_prefetch_guard_bytes
            ),
            "channels": sorted(source_channels),
            "prefetch_guard_bytes": source_prefetch_guard_bytes,
        },
        "vertex_state": {
            "base_bytes": int(parameters["grasu_vertex_state_base_bytes"]),
            "size_bytes": _align_up(
                padded_vertices * source_state_bytes_per_vertex(parameters), 64
            ),
            "channels": [apply_channel],
        },
        "degree": {
            "base_bytes": int(parameters["grasu_degree_base_bytes"]),
            "size_bytes": _align_up(padded_vertices * 4, 64),
            "channels": [degree_channel],
        },
    }

    if packed:
        for name in ("binary", "row", "pma"):
            region = packed_regions[name]
            windows[name]["partition_bases"] = region[2]
            windows[name]["partition_sizes"] = region[3]
        windows["source_state"]["buffer_stride_bytes"] = source_stride

    for name, window in windows.items():
        base = int(window["base_bytes"])
        size = int(window["size_bytes"])
        end = base + size
        if base < 0 or size < 0 or (not interleaved and end > channel_bytes):
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
    if interleaved:
        _attach_interleaved_arena(parameters, windows, channel_bytes)
    return windows
