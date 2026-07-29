"""Fail-closed sparse SST bindings for physical HBM pseudo-channels."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, Mapping

from spine_cycle_sim.experiments.shared_workloads import load_slice


@dataclass(frozen=True)
class SstMemoryBinding:
    """Physical HBM namespace plus the controllers instantiated by SST."""

    physical_channels: int
    reachable_channels: tuple[int, ...]
    instantiated_channels: tuple[int, ...]

    def __post_init__(self) -> None:
        _validate_channels(
            self.reachable_channels,
            self.physical_channels,
            "reachable_channels",
        )
        _validate_channels(
            self.instantiated_channels,
            self.physical_channels,
            "instantiated_channels",
        )
        if not set(self.reachable_channels).issubset(self.instantiated_channels):
            raise ValueError("instantiated HBM channels omit a reachable channel")

    @property
    def sparse(self) -> bool:
        return len(self.instantiated_channels) != self.physical_channels

    @property
    def energy_claim(self) -> str:
        if self.sparse:
            return "bound_channel_dramsim3_only_excludes_unbound_idle_background"
        return "all_physical_channel_dramsim3"

    def as_manifest(self) -> dict[str, object]:
        return {
            "physical_channels": self.physical_channels,
            "reachable_channels": list(self.reachable_channels),
            "instantiated_channels": list(self.instantiated_channels),
            "unbound_request_policy": "fatal",
            "channel_numbers_preserved": True,
            "timing_claim": (
                "host_runtime_optimization_only_physical_architecture_unchanged"
            ),
            "dram_energy_claim": self.energy_claim,
        }


def _validate_channels(
    channels: tuple[int, ...], physical_channels: int, name: str
) -> None:
    if physical_channels <= 0:
        raise ValueError("physical HBM channel count must be positive")
    if not channels:
        raise ValueError(f"{name} must not be empty")
    if tuple(sorted(set(channels))) != channels:
        raise ValueError(f"{name} must be sorted and unique")
    if channels[0] < 0 or channels[-1] >= physical_channels:
        raise ValueError(f"{name} contains an out-of-range physical channel")


def _profile_sections(
    profile: Mapping[str, object],
) -> tuple[Mapping[str, object], Mapping[str, object]]:
    memory = profile.get("memory")
    parameters = profile.get("parameters")
    if not isinstance(memory, Mapping) or not isinstance(parameters, Mapping):
        raise ValueError("architecture profile requires memory and parameters objects")
    return memory, parameters


def make_sst_memory_binding(
    physical_channels: int,
    reachable_channels: Iterable[int],
    *,
    instantiate_all: bool,
) -> SstMemoryBinding:
    reachable = tuple(sorted(set(reachable_channels)))
    instantiated = (
        tuple(range(physical_channels)) if instantiate_all else reachable
    )
    return SstMemoryBinding(physical_channels, reachable, instantiated)


def grasu_normalized_memory_binding(
    profile: Mapping[str, object], *, instantiate_all: bool = False
) -> SstMemoryBinding:
    """Bind the fixed PMA/ReGraph channels reachable by a normalized profile."""

    memory, parameters = _profile_sections(profile)
    physical_channels = int(memory["channels"])
    if (
        parameters.get("grasu_partition_address_layout")
        == "runtime_packed_interleaved_v2"
    ):
        first = int(parameters["grasu_interleaved_hbm_first_channel"])
        count = int(parameters["grasu_interleaved_hbm_channels"])
        return make_sst_memory_binding(
            physical_channels,
            range(first, first + count),
            instantiate_all=instantiate_all,
        )
    pma_channels = int(parameters["grasu_pma_hbm_channels"])
    if pma_channels <= 0:
        raise ValueError("GraSU PMA channel count must be positive")
    reachable = set(range(pma_channels))
    for key in (
        "regraph_source_state_channel",
        "regraph_source_state_mirror_channel",
        "regraph_apply_state_channel",
        "regraph_degree_channel",
    ):
        if key in parameters:
            reachable.add(int(parameters[key]))
    # The normalized PMA row offsets and edge payload both live on channel 0.
    reachable.add(0)
    return make_sst_memory_binding(
        physical_channels, reachable, instantiate_all=instantiate_all
    )


def _spine_hot_hash(destination: int) -> int:
    value = destination & 0xFFFF_FFFF
    value ^= value >> 16
    value = (value * 0x7FEB_352D) & 0xFFFF_FFFF
    value ^= value >> 15
    value = (value * 0x846C_A68B) & 0xFFFF_FFFF
    value ^= value >> 16
    return value & 0xFFFF_FFFF


def spine_memory_binding(
    profile: Mapping[str, object],
    workload_paths: Iterable[Path],
    *,
    hot_vertices: Iterable[int] = (),
    physical_channels: int | None = None,
    instantiate_all: bool = False,
) -> SstMemoryBinding:
    """Derive fixed control channels and graph banks reachable by a Spine run."""

    memory, parameters = _profile_sections(profile)
    profile_channels = int(memory["channels"])
    channels = profile_channels if physical_channels is None else physical_channels
    if channels != profile_channels:
        raise ValueError(
            "Spine SST physical channels must match the architecture profile"
        )
    partitions = int(parameters["partitions"])
    graph_channels = int(parameters["graph_hbm_channels"])
    partition_vertices = int(parameters["vertex_partition_size"])
    hot_shards = int(parameters["hot_shards"])
    if partitions != graph_channels or hot_shards != graph_channels:
        raise ValueError("Spine graph banks must match cold partitions and hot shards")
    if partition_vertices <= 0 or graph_channels <= 0:
        raise ValueError("invalid Spine graph-bank profile")

    reachable = {
        int(parameters[key])
        for key in (
            "sorted_edges_hbm_channel",
            "vertex_state_hbm_channel",
            "active_bins_hbm_channel",
            "active_out_hbm_channel",
            "metadata_hbm_channel",
            "result_hbm_channel",
            "active_bitmap_hbm_channel",
        )
    }
    hot = set(hot_vertices)
    paths = tuple(path.resolve() for path in workload_paths)
    if not paths:
        raise ValueError("Spine memory binding requires at least one workload")
    for path in paths:
        graph = load_slice(path)
        for edge in graph.records:
            if edge.dst in hot:
                family = _spine_hot_hash(edge.dst) % hot_shards
            else:
                family = min(edge.dst // partition_vertices, partitions - 1)
            reachable.add(family)
    return make_sst_memory_binding(
        channels, reachable, instantiate_all=instantiate_all
    )
