"""Spine cycle-level architecture model.

The public class is still named ``SpineV0Simulator`` for script compatibility,
but the model now follows the current ``reduce-levels-for-routing`` Spine
baseline:

* 11 ratio-2 binary levels
* 16 destination-partition cold families
* 16 hashed hot-destination shards
* graph-agnostic hot/cold classification from measured destination in-degree
* split read-maintenance / convergence behavior with tiny-active counters
"""

from __future__ import annotations

from collections import defaultdict, deque
from dataclasses import asdict, dataclass
from math import ceil
from pathlib import Path
from typing import Any, Callable, Deque, Optional

from spine_cycle_sim.core.component import Component
from spine_cycle_sim.core.fifo import FifoLink
from spine_cycle_sim.core.memory import HBMPartition, MemoryRequest
from spine_cycle_sim.core.simulator import CycleSimulator
from spine_cycle_sim.core.stats import Stats
from spine_cycle_sim.models.dstage import build_tile_schedule
from spine_cycle_sim.workloads import Edge, Workload


@dataclass
class SpineConfig:
    max_vertices: int = 16_777_216
    vs_partition_size: int = 1_048_576
    num_partitions: int = 16
    hot_shards: int = 16
    hot_cold_enabled: bool = True
    target_freq_mhz: float = 134.0
    fifo_depth: int = 32
    max_cycles: int = 20_000_000
    edge_input_ii: int = 1
    router_ii: int = 1
    level0_accept_edges_per_cycle: int = 16
    batch_size_edges: int = 131_072
    num_levels: int = 11
    level_size_ratio: int = 2
    carry_merge_edges_per_cycle: int = 16
    hbm_channel_bytes: int = 512 * 1024 * 1024
    hbm_latency_cycles: int = 200
    hbm_read_bw_edges_per_cycle: int = 16
    hbm_write_bw_edges_per_cycle: int = 16
    csr_vertices_per_page: int = 256
    readmaintenance_vertex_scan_rate: int = 64
    conv_tile_vertices: int = 65_536
    conv_tile_replay_fallback_threshold: int = 65_536
    conv_tile_touch_fallback_threshold: int = 16
    tiny_active_threshold: int = 4096
    sssp_pipeline_ii: int = 1
    sssp_edges_per_cycle: int = 1
    maintenance_calibrated_timing: bool = True
    maintenance_schedule_calibrated_cycles: bool = False
    maintenance_l0_scan_iteration_cycles: int = 105
    maintenance_l0_output_edge_cycles: int = 110
    maintenance_carry_scan_iteration_cycles: int = 145
    maintenance_carry_payload_output_edge_cycles: int = 80
    maintenance_carry_row_cursor_cycles: int = 130
    maintenance_refill_stalls_per_page: int = 261
    maintenance_refill_stall_cycles: int = 1

    @property
    def hot_family_base(self) -> int:
        return self.num_partitions

    @property
    def family_count(self) -> int:
        return self.num_partitions + (self.hot_shards if self.hot_cold_enabled else 0)

    @property
    def level_capacity_per_family(self) -> dict[int, int]:
        return {level: self.level_family_capacity(level) for level in range(self.num_levels)}

    @property
    def level_capacity_per_partition(self) -> dict[int, int]:
        return self.level_capacity_per_family

    @property
    def family_total_capacity(self) -> int:
        return sum(self.level_family_capacity(level) for level in range(self.num_levels))

    @property
    def level1_capacity_per_partition(self) -> int:
        return self.level_family_capacity(1)

    def level_total_capacity(self, level: int) -> int:
        return self.batch_size_edges * (self.level_size_ratio ** level)

    def level_family_capacity(self, level: int) -> int:
        if level == 0:
            return self.batch_size_edges
        return ceil(self.level_total_capacity(level) / self.num_partitions)

    def partition_for_dst(self, dst: int) -> int:
        part = dst // max(1, self.vs_partition_size)
        return max(0, min(self.num_partitions - 1, part))

    def hot_shard_for_dst(self, dst: int) -> int:
        return hot_dst_hash(dst) % max(1, self.hot_shards)


def _parse_scalar(value: str) -> int | float | bool | str:
    value = value.strip()
    if value.lower() in {"true", "false"}:
        return value.lower() == "true"
    try:
        return int(value.replace("_", ""))
    except ValueError:
        pass
    try:
        return float(value)
    except ValueError:
        return value.strip("\"'")


def load_config(path: str | Path) -> SpineConfig:
    """Load a flat YAML-like config without external dependencies."""

    data: dict[str, Any] = {}
    for raw_line in Path(path).read_text(encoding="utf-8").splitlines():
        line = raw_line.split("#", 1)[0].strip()
        if not line:
            continue
        if ":" not in line:
            raise ValueError(f"unsupported config line: {raw_line}")
        key, value = line.split(":", 1)
        data[key.strip()] = _parse_scalar(value)
    known = set(SpineConfig.__dataclass_fields__)
    unknown = sorted(set(data) - known)
    if unknown:
        raise ValueError(f"unknown config keys: {', '.join(unknown)}")
    return SpineConfig(**data)


def hot_dst_hash(dst: int) -> int:
    x = dst & 0xFFFFFFFF
    x ^= x >> 16
    x = (x * 0x7FEB352D) & 0xFFFFFFFF
    x ^= x >> 15
    x = (x * 0x846CA68B) & 0xFFFFFFFF
    x ^= x >> 16
    return x & 0xFFFFFFFF


@dataclass
class HotColdClassification:
    hot_dsts: set[int]
    cold_partition_edges: list[int]
    hot_shard_edges: list[int]
    total_edges: int
    hot_edges: int
    cold_edges: int
    hot_vertex_count: int
    empty_hot_set: bool
    family_edge_cap: int


def classify_hot_cold(edges: list[Edge], config: SpineConfig) -> HotColdClassification:
    """Mirror the host measured-in-degree hot/cold classifier at model scale."""

    cold_counts = [0 for _ in range(config.num_partitions)]
    hot_counts = [0 for _ in range(config.hot_shards)]
    indegree: dict[int, int] = defaultdict(int)
    for edge in edges:
        if edge.dst >= config.max_vertices:
            raise ValueError(f"dst {edge.dst} exceeds max_vertices={config.max_vertices}")
        indegree[edge.dst] += 1

    candidates: list[tuple[int, int]] = []
    for dst, degree in indegree.items():
        if degree > config.family_total_capacity:
            raise ValueError(
                f"super-hub destination {dst} indegree={degree} "
                f"exceeds hot shard cap={config.family_total_capacity}"
            )
        cold_counts[config.partition_for_dst(dst)] += degree
        candidates.append((degree, dst))

    total = sum(indegree.values())
    if (
        not config.hot_cold_enabled
        or all(count <= config.family_total_capacity for count in cold_counts)
    ):
        return HotColdClassification(
            hot_dsts=set(),
            cold_partition_edges=cold_counts,
            hot_shard_edges=hot_counts,
            total_edges=total,
            hot_edges=0,
            cold_edges=total,
            hot_vertex_count=0,
            empty_hot_set=True,
            family_edge_cap=config.family_total_capacity,
        )

    hot_dsts: set[int] = set()
    hot_edges = 0
    candidates.sort(key=lambda item: (-item[0], item[1]))
    for degree, dst in candidates:
        if all(count <= config.family_total_capacity for count in cold_counts):
            break
        partition = config.partition_for_dst(dst)
        if cold_counts[partition] <= config.family_total_capacity:
            continue
        shard = config.hot_shard_for_dst(dst)
        hot_dsts.add(dst)
        hot_edges += degree
        cold_counts[partition] -= degree
        hot_counts[shard] += degree
        if hot_counts[shard] > config.family_total_capacity:
            raise ValueError(
                f"hot shard {shard} capacity exceeded: "
                f"{hot_counts[shard]} > {config.family_total_capacity}"
            )

    if any(count > config.family_total_capacity for count in cold_counts):
        raise ValueError("hot/cold classifier could not fit cold partitions")

    return HotColdClassification(
        hot_dsts=hot_dsts,
        cold_partition_edges=cold_counts,
        hot_shard_edges=hot_counts,
        total_edges=total,
        hot_edges=hot_edges,
        cold_edges=total - hot_edges,
        hot_vertex_count=len(hot_dsts),
        empty_hot_set=len(hot_dsts) == 0,
        family_edge_cap=config.family_total_capacity,
    )


@dataclass(frozen=True)
class EdgePacket:
    edge: Edge
    sequence: int
    family: int = -1


@dataclass(frozen=True)
class FamilyBatchStats:
    input_edges: int
    unique_edges: int
    rows: int
    pages: int


@dataclass(frozen=True)
class MaintenanceEstimate:
    group: str
    path: str
    target_level: int
    batch_edges: int
    input_edges: int
    output_edges: int
    family_count: int
    nonempty_input_families: int
    nonempty_output_families: int
    diagnostic_scan_passes: int
    pre_count_scan_passes: int
    write_scan_passes: int
    new_batch_filter_passes: int
    scan_passes: int
    scan_cycles: int
    cursor_level_inits: int
    pages_visited: int
    bits_inspected: int
    rows_entered: int
    payload_reads: int
    cursor_read_cycles: int
    merge_inputs: int
    outputs: int
    page_ids_written: int
    write_output_cycles: int
    metadata_cycles: int
    refill_stalls: int
    validation_failures: int
    structural_estimated_cycles: int
    calibrated_scan_cycles: int
    calibrated_merge_cycles: int
    calibrated_row_cursor_cycles: int
    calibrated_refill_stall_cycles: int
    calibrated_write_output_cycles: int
    calibrated_metadata_cycles: int
    calibrated_estimated_cycles: int
    scheduled_cycles: int
    estimated_cycles: int


@dataclass(frozen=True)
class StorageEvent:
    target_level: int
    family_base: int
    family_count: int
    counts_by_family: tuple[int, ...]
    edge_count: int
    carry: bool
    group: str
    tag: str
    maintenance: MaintenanceEstimate


class EdgeInput(Component):
    def __init__(
        self,
        edges: list[Edge],
        output: FifoLink[EdgePacket],
        stats: Stats,
        edge_input_ii: int,
    ) -> None:
        super().__init__("EdgeInput")
        self.edges = edges
        self.output = output
        self.stats = stats
        self.edge_input_ii = max(1, edge_input_ii)
        self.index = 0
        self.next_emit_cycle = 0

    @property
    def done(self) -> bool:
        return self.index >= len(self.edges)

    def evaluate(self, cycle: int) -> None:
        if self.done or cycle < self.next_emit_cycle:
            return
        if not self.output.can_push():
            self.stats.inc("edge_input_stall_cycles")
            return
        packet = EdgePacket(self.edges[self.index], self.index)
        if self.output.request_push(packet):
            self.stats.inc("edge_input_emitted")
            self.index += 1
            self.next_emit_cycle = cycle + self.edge_input_ii


class PartitionRouter(Component):
    def __init__(
        self,
        input_fifo: FifoLink[EdgePacket],
        outputs: list[FifoLink[EdgePacket]],
        stats: Stats,
        config: SpineConfig,
        hot_dsts: set[int],
        router_ii: int,
    ) -> None:
        super().__init__("PartitionRouter")
        self.input_fifo = input_fifo
        self.outputs = outputs
        self.stats = stats
        self.config = config
        self.hot_dsts = hot_dsts
        self.router_ii = max(1, router_ii)
        self.next_route_cycle = 0
        self.upstream_done: Callable[[], bool] = lambda: False

    @property
    def done(self) -> bool:
        return self.upstream_done() and self.input_fifo.empty

    def _family_for_edge(self, edge: Edge) -> int:
        if self.config.hot_cold_enabled and edge.dst in self.hot_dsts:
            return self.config.hot_family_base + self.config.hot_shard_for_dst(edge.dst)
        return self.config.partition_for_dst(edge.dst)

    def evaluate(self, cycle: int) -> None:
        if cycle < self.next_route_cycle:
            return
        packet = self.input_fifo.peek()
        if packet is None:
            return
        family = self._family_for_edge(packet.edge)
        output = self.outputs[family]
        if not output.can_push():
            self.stats.inc("router_output_stall_cycles")
            return
        popped = self.input_fifo.request_pop()
        if popped is None:
            return
        output.request_push(EdgePacket(popped.edge, popped.sequence, family))
        self.stats.inc("router_routed_edges")
        self.stats.inc(f"family.{family}.routed_edges")
        if family >= self.config.hot_family_base:
            self.stats.inc("router_hot_edges")
        else:
            self.stats.inc("router_cold_edges")
        self.next_route_cycle = cycle + self.router_ii


class Level0Buffer(Component):
    def __init__(
        self,
        inputs: list[FifoLink[EdgePacket]],
        event_fifo: FifoLink[StorageEvent],
        stats: Stats,
        config: SpineConfig,
        upstream_done: Callable[[], bool],
        metadata_hot_enabled: bool,
    ) -> None:
        super().__init__("Level0Buffer")
        self.inputs = inputs
        self.event_fifo = event_fifo
        self.stats = stats
        self.config = config
        self.upstream_done = upstream_done
        self.metadata_hot_enabled = metadata_hot_enabled
        self.current_counts = [0 for _ in range(config.family_count)]
        self.current_edge_keys = [set() for _ in range(config.family_count)]
        self.current_rows = [set() for _ in range(config.family_count)]
        self.current_pages = [set() for _ in range(config.family_count)]
        self.level_counts = [
            [0 for _ in range(config.num_levels)] for _ in range(config.family_count)
        ]
        self.level_row_counts = [
            [0 for _ in range(config.num_levels)] for _ in range(config.family_count)
        ]
        self.level_page_counts = [
            [0 for _ in range(config.num_levels)] for _ in range(config.family_count)
        ]
        self.level_page_sets = [
            [set() for _ in range(config.num_levels)] for _ in range(config.family_count)
        ]
        self.current_edges = 0
        self._pending_events: Deque[StorageEvent] = deque()
        self._rr_family = 0
        self.maintenance_events: list[MaintenanceEstimate] = []

    @property
    def done(self) -> bool:
        return (
            self.upstream_done()
            and all(fifo.empty for fifo in self.inputs)
            and self.current_edges == 0
            and not self._pending_events
        )

    def evaluate(self, cycle: int) -> None:
        if self._pending_events:
            event = self._pending_events[0]
            if self.event_fifo.request_push(event):
                self.stats.add_trace(
                    cycle,
                    "level_emit_storage_event",
                    target_level=event.target_level,
                    edge_count=event.edge_count,
                    carry=event.carry,
                    group=event.group,
                    maintenance_path=event.maintenance.path,
                    estimated_cycles=event.maintenance.estimated_cycles,
                    scan_passes=event.maintenance.scan_passes,
                )
                self._pending_events.popleft()
            return

        accepted = 0
        budget = max(1, self.config.level0_accept_edges_per_cycle)
        for offset in range(self.config.family_count):
            if accepted >= budget:
                break
            family = (self._rr_family + offset) % self.config.family_count
            packet = self.inputs[family].request_pop()
            if packet is None:
                continue
            self._record_current_packet(packet)
            self.current_edges += 1
            accepted += 1
            self.stats.inc("level0_accepted_edges")
            self.stats.max_value("level0.current_batch_edges.max", self.current_edges)
            if self.current_edges >= self.config.batch_size_edges:
                self._prepare_flush("full_batch")
                break
        self._rr_family = (self._rr_family + 1) % self.config.family_count

        if (
            not self._pending_events
            and self.current_edges > 0
            and self.upstream_done()
            and all(fifo.empty for fifo in self.inputs)
        ):
            self._prepare_flush("final_batch")

    def _prepare_flush(self, tag: str) -> None:
        batch_edges = self.current_edges
        include_diagnostic = True
        self._apply_group(
            0,
            self.config.num_partitions,
            "cold",
            tag,
            batch_edges,
            include_diagnostic,
        )
        include_diagnostic = False
        if self.stats.failure is not None:
            self._reset_current_batch()
            return
        if self.metadata_hot_enabled:
            self._apply_group(
                self.config.hot_family_base,
                self.config.hot_shards,
                "hot",
                tag,
                batch_edges,
                include_diagnostic,
            )
        self._reset_current_batch()

    def _apply_group(
        self,
        family_base: int,
        family_count: int,
        group: str,
        tag: str,
        batch_edges: int,
        include_diagnostic: bool,
    ) -> None:
        families = range(family_base, family_base + family_count)
        group_stats = {family: self._current_family_stats(family) for family in families}
        group_input = sum(stat.input_edges for stat in group_stats.values())
        target = self._select_capacity_safe_target(
            family_base, family_count, group_stats
        )
        if target < 0:
            self.stats.set_failure(
                "level_exhausted",
                group=group,
                maintenance_path="overflow",
                batch_edges=batch_edges,
            )
            return
        combined_edges = [0 for _ in range(self.config.family_count)]
        combined_rows = [0 for _ in range(self.config.family_count)]
        combined_pages = [0 for _ in range(self.config.family_count)]
        combined_page_sets = [set() for _ in range(self.config.family_count)]
        old_edges_by_family = [0 for _ in range(self.config.family_count)]
        old_rows_by_family = [0 for _ in range(self.config.family_count)]
        old_pages_by_family = [0 for _ in range(self.config.family_count)]

        for family in families:
            stat = group_stats[family]
            edge_count = stat.unique_edges
            row_count = stat.rows
            page_set = set(self.current_pages[family])
            for level in range(target):
                old_edges_by_family[family] += self.level_counts[family][level]
                old_rows_by_family[family] += self.level_row_counts[family][level]
                old_pages_by_family[family] += self.level_page_counts[family][level]
                page_set.update(self.level_page_sets[family][level])
            edge_count += old_edges_by_family[family]
            row_count += old_rows_by_family[family]
            page_count = len(page_set)
            if edge_count > self.config.level_family_capacity(target):
                self.stats.set_failure(
                    "level_family_capacity",
                    failure_level=target,
                    failure_family=family,
                    failure_partition=family % self.config.num_partitions,
                    failure_partition_edges=edge_count,
                    failure_partition_capacity=self.config.level_family_capacity(target),
                    group=group,
                    maintenance_path="cascade" if target > 0 else "store_l0",
                    batch_edges=batch_edges,
                    group_input_edges=group_input,
                )
                self.stats.inc("maintenance_overflow_events")
                return
            combined_edges[family] = edge_count
            combined_rows[family] = row_count
            combined_pages[family] = page_count
            combined_page_sets[family] = page_set

        for family in families:
            for level in range(target):
                self.level_counts[family][level] = 0
                self.level_row_counts[family][level] = 0
                self.level_page_counts[family][level] = 0
                self.level_page_sets[family][level] = set()
            self.level_counts[family][target] = combined_edges[family]
            self.level_row_counts[family][target] = combined_rows[family]
            self.level_page_counts[family][target] = combined_pages[family]
            self.level_page_sets[family][target] = combined_page_sets[family]
            for level, value in enumerate(self.level_counts[family]):
                self.stats.max_value(f"family.{family}.level{level}.max_occupancy", value)

        edge_count = sum(combined_edges)
        carry = target > 0
        if carry:
            self.stats.inc("carry_count")
            self.stats.inc(f"{group}_carry_count")
        estimate = self._estimate_maintenance(
            group=group,
            target=target,
            batch_edges=batch_edges,
            include_diagnostic=include_diagnostic,
            group_stats=group_stats,
            combined_edges=combined_edges,
            combined_rows=combined_rows,
            combined_pages=combined_pages,
            old_edges_by_family=old_edges_by_family,
            old_rows_by_family=old_rows_by_family,
            old_pages_by_family=old_pages_by_family,
            family_base=family_base,
            family_count=family_count,
        )
        self._record_maintenance_estimate(estimate)
        self.stats.max_value(f"{group}.max_target_level", target)
        self.stats.max_value(f"level{target}.logical_occupancy.max", edge_count)
        self._pending_events.append(
            StorageEvent(
                target_level=target,
                family_base=family_base,
                family_count=family_count,
                counts_by_family=tuple(combined_edges),
                edge_count=edge_count,
                carry=carry,
                group=group,
                tag=tag,
                maintenance=estimate,
            )
        )

    def _record_current_packet(self, packet: EdgePacket) -> None:
        family = packet.family
        edge = packet.edge
        self.current_counts[family] += 1
        self.current_edge_keys[family].add((edge.src, edge.dst))
        self.current_rows[family].add(edge.src)
        page_size = max(1, self.config.csr_vertices_per_page)
        self.current_pages[family].add(edge.src // page_size)

    def _current_family_stats(self, family: int) -> FamilyBatchStats:
        return FamilyBatchStats(
            input_edges=self.current_counts[family],
            unique_edges=len(self.current_edge_keys[family]),
            rows=len(self.current_rows[family]),
            pages=len(self.current_pages[family]),
        )

    def _reset_current_batch(self) -> None:
        self.current_counts = [0 for _ in range(self.config.family_count)]
        self.current_edge_keys = [set() for _ in range(self.config.family_count)]
        self.current_rows = [set() for _ in range(self.config.family_count)]
        self.current_pages = [set() for _ in range(self.config.family_count)]
        self.current_edges = 0

    def _estimate_maintenance(
        self,
        group: str,
        target: int,
        batch_edges: int,
        include_diagnostic: bool,
        group_stats: dict[int, FamilyBatchStats],
        combined_edges: list[int],
        combined_rows: list[int],
        combined_pages: list[int],
        old_edges_by_family: list[int],
        old_rows_by_family: list[int],
        old_pages_by_family: list[int],
        family_base: int,
        family_count: int,
    ) -> MaintenanceEstimate:
        families = range(family_base, family_base + family_count)
        input_edges = sum(stat.input_edges for stat in group_stats.values())
        input_unique_edges = sum(stat.unique_edges for stat in group_stats.values())
        output_edges = sum(combined_edges[family] for family in families)
        output_rows = sum(combined_rows[family] for family in families)
        output_pages = sum(combined_pages[family] for family in families)
        old_edges = sum(old_edges_by_family[family] for family in families)
        old_rows = sum(old_rows_by_family[family] for family in families)
        old_pages = sum(old_pages_by_family[family] for family in families)
        diagnostic_scan_passes = 1 if include_diagnostic else 0
        nonempty_input = sum(1 for stat in group_stats.values() if stat.input_edges > 0)
        nonempty_output = sum(1 for family in families if combined_edges[family] > 0)
        path = "cascade" if target > 0 else "store_l0"

        pre_count_scan_passes = 0
        write_scan_passes = 0
        new_batch_filter_passes = 0
        cursor_level_inits = 0
        pages_visited = 0
        bits_inspected = 0
        rows_entered = 0
        payload_reads = 0
        cursor_read_cycles = 0
        merge_inputs = 0
        metadata_cycles = 0
        refill_stalls = 0

        if target == 0:
            pre_count_scan_passes = family_count
            write_scan_passes = nonempty_output
            metadata_cycles = family_count
        else:
            new_batch_filter_passes = family_count
            cursor_level_inits = family_count * target
            pages_visited = old_pages
            bits_inspected = old_pages * max(1, self.config.csr_vertices_per_page)
            rows_entered = old_rows
            payload_reads = old_edges
            refill_stalls = old_pages * self.config.maintenance_refill_stalls_per_page
            cursor_read_cycles = old_pages * 7 + old_rows * 2 + old_edges
            merge_inputs = old_edges + input_unique_edges
            metadata_cycles = cursor_level_inits * 8 + family_count * 21

        scan_passes = (
            diagnostic_scan_passes
            + pre_count_scan_passes
            + write_scan_passes
            + new_batch_filter_passes
        )
        scan_cycles = scan_passes * batch_edges
        write_output_cycles = output_edges + output_rows + output_pages
        estimated_cycles = (
            scan_cycles
            + cursor_read_cycles
            + bits_inspected
            + merge_inputs
            + write_output_cycles
            + metadata_cycles
        )
        structural_estimated_cycles = estimated_cycles
        if self.config.maintenance_calibrated_timing:
            if target == 0:
                calibrated_scan_cycles = (
                    scan_cycles * self.config.maintenance_l0_scan_iteration_cycles
                )
                calibrated_merge_cycles = 0
                calibrated_row_cursor_cycles = 0
                calibrated_refill_stall_cycles = 0
                calibrated_write_output_cycles = (
                    output_edges * self.config.maintenance_l0_output_edge_cycles
                    + output_rows
                    + output_pages
                )
            else:
                calibrated_scan_cycles = (
                    scan_cycles * self.config.maintenance_carry_scan_iteration_cycles
                )
                calibrated_merge_cycles = (
                    (payload_reads + output_edges)
                    * self.config.maintenance_carry_payload_output_edge_cycles
                )
                calibrated_row_cursor_cycles = (
                    rows_entered * self.config.maintenance_carry_row_cursor_cycles
                )
                calibrated_refill_stall_cycles = (
                    refill_stalls * self.config.maintenance_refill_stall_cycles
                )
                calibrated_write_output_cycles = output_pages
            calibrated_metadata_cycles = metadata_cycles
            calibrated_estimated_cycles = (
                calibrated_scan_cycles
                + calibrated_merge_cycles
                + calibrated_row_cursor_cycles
                + calibrated_refill_stall_cycles
                + calibrated_write_output_cycles
                + calibrated_metadata_cycles
            )
        else:
            calibrated_scan_cycles = scan_cycles
            calibrated_merge_cycles = merge_inputs
            calibrated_row_cursor_cycles = cursor_read_cycles
            calibrated_refill_stall_cycles = 0
            calibrated_write_output_cycles = write_output_cycles
            calibrated_metadata_cycles = metadata_cycles
            calibrated_estimated_cycles = structural_estimated_cycles
        scheduled_cycles = (
            calibrated_estimated_cycles
            if self.config.maintenance_schedule_calibrated_cycles
            else structural_estimated_cycles
        )
        return MaintenanceEstimate(
            group=group,
            path=path,
            target_level=target,
            batch_edges=batch_edges,
            input_edges=input_edges,
            output_edges=output_edges,
            family_count=family_count,
            nonempty_input_families=nonempty_input,
            nonempty_output_families=nonempty_output,
            diagnostic_scan_passes=diagnostic_scan_passes,
            pre_count_scan_passes=pre_count_scan_passes,
            write_scan_passes=write_scan_passes,
            new_batch_filter_passes=new_batch_filter_passes,
            scan_passes=scan_passes,
            scan_cycles=scan_cycles,
            cursor_level_inits=cursor_level_inits,
            pages_visited=pages_visited,
            bits_inspected=bits_inspected,
            rows_entered=rows_entered,
            payload_reads=payload_reads,
            cursor_read_cycles=cursor_read_cycles,
            merge_inputs=merge_inputs,
            outputs=output_edges,
            page_ids_written=output_pages,
            write_output_cycles=write_output_cycles,
            metadata_cycles=metadata_cycles,
            refill_stalls=refill_stalls,
            validation_failures=0,
            structural_estimated_cycles=structural_estimated_cycles,
            calibrated_scan_cycles=calibrated_scan_cycles,
            calibrated_merge_cycles=calibrated_merge_cycles,
            calibrated_row_cursor_cycles=calibrated_row_cursor_cycles,
            calibrated_refill_stall_cycles=calibrated_refill_stall_cycles,
            calibrated_write_output_cycles=calibrated_write_output_cycles,
            calibrated_metadata_cycles=calibrated_metadata_cycles,
            calibrated_estimated_cycles=calibrated_estimated_cycles,
            scheduled_cycles=scheduled_cycles,
            estimated_cycles=calibrated_estimated_cycles,
        )

    def _record_maintenance_estimate(self, estimate: MaintenanceEstimate) -> None:
        self.maintenance_events.append(estimate)
        prefix = f"maintenance.{estimate.group}"
        self.stats.inc("maintenance_event_count")
        self.stats.inc(f"{prefix}.event_count")
        self.stats.inc(f"maintenance_{estimate.path}_events")
        self.stats.inc(f"{prefix}.{estimate.path}_events")
        self.stats.inc("maintenance_estimated_cycles", estimate.estimated_cycles)
        self.stats.inc("maintenance_structural_estimated_cycles", estimate.structural_estimated_cycles)
        self.stats.inc("maintenance_calibrated_estimated_cycles", estimate.calibrated_estimated_cycles)
        self.stats.inc("maintenance_scan_passes", estimate.scan_passes)
        self.stats.inc("maintenance_scan_cycles", estimate.scan_cycles)
        self.stats.inc("maintenance_calibrated_scan_cycles", estimate.calibrated_scan_cycles)
        self.stats.inc("maintenance_cursor_read_cycles", estimate.cursor_read_cycles)
        self.stats.inc("maintenance_bits_inspected", estimate.bits_inspected)
        self.stats.inc("maintenance_payload_reads", estimate.payload_reads)
        self.stats.inc("maintenance_refill_stalls", estimate.refill_stalls)
        self.stats.inc("maintenance_merge_inputs", estimate.merge_inputs)
        self.stats.inc("maintenance_outputs", estimate.outputs)
        self.stats.inc("maintenance_page_ids_written", estimate.page_ids_written)
        self.stats.inc("maintenance_write_output_cycles", estimate.write_output_cycles)
        self.stats.inc("maintenance_calibrated_merge_cycles", estimate.calibrated_merge_cycles)
        self.stats.inc(
            "maintenance_calibrated_row_cursor_cycles",
            estimate.calibrated_row_cursor_cycles,
        )
        self.stats.inc(
            "maintenance_calibrated_refill_stall_cycles",
            estimate.calibrated_refill_stall_cycles,
        )
        self.stats.inc(
            "maintenance_calibrated_write_output_cycles",
            estimate.calibrated_write_output_cycles,
        )
        self.stats.max_value("maintenance.max_target_level", estimate.target_level)
        self.stats.max_value(f"{prefix}.max_target_level", estimate.target_level)

    def _select_capacity_safe_target(
        self,
        family_base: int,
        family_count: int,
        group_stats: dict[int, FamilyBatchStats],
    ) -> int:
        cumulative = {
            family: group_stats[family].input_edges
            for family in range(family_base, family_base + family_count)
        }
        for level in range(self.config.num_levels):
            occupied = any(
                self.level_counts[family][level] > 0
                for family in range(family_base, family_base + family_count)
            )
            if not occupied:
                capacity = self.config.level_family_capacity(level)
                if all(count <= capacity for count in cumulative.values()):
                    return level
                self.stats.inc("target_selector_capacity_skips")
                continue
            for family in range(family_base, family_base + family_count):
                cumulative[family] += self.level_counts[family][level]
        return -1


class Level1CarryMerge(Component):
    def __init__(
        self,
        input_fifo: FifoLink[StorageEvent],
        memory_fifos: list[FifoLink[MemoryRequest]],
        stats: Stats,
        config: SpineConfig,
        upstream_done: Callable[[], bool],
    ) -> None:
        super().__init__("Level1CarryMerge")
        self.input_fifo = input_fifo
        self.memory_fifos = memory_fifos
        self.stats = stats
        self.config = config
        self.upstream_done = upstream_done
        self._event: Optional[StorageEvent] = None
        self._ready_cycle = 0
        self._family_index = 0

    @property
    def done(self) -> bool:
        return self.upstream_done() and self.input_fifo.empty and self._event is None

    def evaluate(self, cycle: int) -> None:
        if self._event is None:
            event = self.input_fifo.request_pop()
            if event is None:
                return
            self._event = event
            self._family_index = event.family_base
            delay = max(0, event.maintenance.scheduled_cycles)
            self._ready_cycle = cycle + delay
            self.stats.inc("maintenance_scheduled_cycles", delay)
            self.stats.add_trace(
                cycle,
                "carry_merge_accept_event",
                target_level=event.target_level,
                edge_count=event.edge_count,
                carry=event.carry,
                group=event.group,
                maintenance_path=event.maintenance.path,
                estimated_cycles=event.maintenance.estimated_cycles,
                scheduled_cycles=event.maintenance.scheduled_cycles,
                scan_passes=event.maintenance.scan_passes,
            )
            return

        if cycle < self._ready_cycle:
            self.stats.inc("carry_merge_busy_cycles")
            return

        end = self._event.family_base + self._event.family_count
        while self._event is not None and self._family_index < end:
            family = self._family_index
            count = self._event.counts_by_family[family]
            if count == 0:
                self._family_index += 1
                continue
            bank = family % self.config.num_partitions
            request = MemoryRequest(
                partition=bank,
                family=family,
                op="write",
                level=self._event.target_level,
                edge_count=count,
                mode="replace",
                clear_lower=self._event.target_level > 0,
                tag=f"{self._event.group}:{self._event.tag}",
            )
            if not self.memory_fifos[bank].request_push(request):
                self.stats.inc("carry_merge_memory_output_stall_cycles")
                return
            self._family_index += 1
        if self._event is not None and self._family_index >= end:
            self.stats.add_trace(
                cycle,
                "carry_merge_emit_memory_requests",
                target_level=self._event.target_level,
                edge_count=self._event.edge_count,
                group=self._event.group,
            )
            self._event = None


class ReadMaintenance(Component):
    def __init__(
        self,
        memory_fifos: list[FifoLink[MemoryRequest]],
        start_fifo: FifoLink[dict[str, int]],
        family_counts: list[int],
        vertices: int,
        stats: Stats,
        config: SpineConfig,
        storage_done: Callable[[], bool],
        memory_idle: Callable[[], bool],
    ) -> None:
        super().__init__("ReadMaintenance")
        self.memory_fifos = memory_fifos
        self.start_fifo = start_fifo
        self.family_counts = family_counts
        self.vertices = vertices
        self.stats = stats
        self.config = config
        self.storage_done = storage_done
        self.memory_idle = memory_idle
        self.state = "waiting"
        self.scan_done_cycle = 0
        self.family_index = 0

    @property
    def done(self) -> bool:
        return self.state == "done"

    def evaluate(self, cycle: int) -> None:
        if self.state == "waiting":
            if self.storage_done() and self.memory_idle():
                scan_cycles = ceil(self.vertices / max(1, self.config.readmaintenance_vertex_scan_rate))
                self.scan_done_cycle = cycle + scan_cycles
                self.stats.inc("readmaintenance_scan_cycles", scan_cycles)
                self.state = "scanning"
            return
        if self.state == "scanning":
            if cycle < self.scan_done_cycle:
                return
            self.state = "issuing_reads"
        if self.state == "issuing_reads":
            while self.family_index < self.config.family_count:
                count = self.family_counts[self.family_index]
                if count == 0:
                    self.family_index += 1
                    continue
                bank = self.family_index % self.config.num_partitions
                request = MemoryRequest(
                    partition=bank,
                    family=self.family_index,
                    op="read",
                    level=0,
                    edge_count=count,
                    tag="readmaintenance",
                )
                if not self.memory_fifos[bank].request_push(request):
                    self.stats.inc("readmaintenance_memory_output_stall_cycles")
                    return
                self.family_index += 1
            self.state = "waiting_reads"
            return
        if self.state == "waiting_reads":
            if self.memory_idle():
                if self.start_fifo.request_push({"edge_count": sum(self.family_counts)}):
                    self.state = "done"


class SSSPCompute(Component):
    def __init__(
        self,
        start_fifo: FifoLink[dict[str, int]],
        output_fifo: FifoLink[dict[str, int]],
        edges: list[Edge],
        source: int,
        stats: Stats,
        config: SpineConfig,
    ) -> None:
        super().__init__("SSSPCompute")
        self.start_fifo = start_fifo
        self.output_fifo = output_fifo
        self.edges = edges
        self.source = source
        self.stats = stats
        self.config = config
        self.graph: dict[int, list[tuple[int, int]]] = defaultdict(list)
        for edge in edges:
            self.graph[edge.src].append((edge.dst, edge.weight))
        self.state = "waiting"
        self.dist: dict[int, int] = {}
        self.frontier: Deque[int] = deque()
        self.next_frontier: Deque[int] = deque()
        self.current_vertex: Optional[int] = None
        self.current_edges: list[tuple[int, int]] = []
        self.edge_index = 0
        self.next_compute_cycle = 0
        self.rounds = 0
        self._pending_result: Optional[dict[str, int]] = None

    @property
    def done(self) -> bool:
        return self.state == "done"

    def evaluate(self, cycle: int) -> None:
        if self.state == "waiting":
            token = self.start_fifo.request_pop()
            if token is not None:
                self._start(cycle)
            return
        if self.state == "emitting":
            if self._pending_result is not None and self.output_fifo.request_push(self._pending_result):
                self.state = "done"
            return
        if self.state != "running":
            return
        if cycle < self.next_compute_cycle:
            self.stats.inc("compute_stall_cycles")
            return
        processed = 0
        budget = max(1, self.config.sssp_edges_per_cycle)
        while processed < budget:
            if self.current_vertex is None:
                if self.frontier:
                    self.current_vertex = self.frontier.popleft()
                    self.current_edges = self.graph.get(self.current_vertex, [])
                    self.edge_index = 0
                elif self.next_frontier:
                    self.frontier, self.next_frontier = self.next_frontier, deque()
                    self._begin_iteration()
                    continue
                else:
                    self._finish()
                    return
            if self.edge_index >= len(self.current_edges):
                self.current_vertex = None
                continue
            dst, weight = self.current_edges[self.edge_index]
            self.edge_index += 1
            processed += 1
            self.stats.inc("sssp_relax_attempts")
            src_dist = self.dist.get(self.current_vertex, 0)
            cand = src_dist + weight
            if cand < self.dist.get(dst, 1 << 60):
                self.dist[dst] = cand
                self.next_frontier.append(dst)
                self.stats.inc("sssp_successful_relaxes")
        self.next_compute_cycle = cycle + max(1, self.config.sssp_pipeline_ii)

    def _start(self, cycle: int) -> None:
        self.state = "running"
        self.dist = {self.source: 0}
        self.frontier = deque([self.source])
        self.next_frontier = deque()
        self.current_vertex = None
        self.current_edges = []
        self.edge_index = 0
        self.rounds = 0
        self.next_compute_cycle = cycle
        self._begin_iteration()
        self.stats.add_trace(cycle, "sssp_start", source=self.source)

    def _begin_iteration(self) -> None:
        self.rounds += 1
        active_count = len(self.frontier)
        self.stats.inc("sssp_iterations")
        self.stats.max_value("sssp.max_frontier", active_count)
        if active_count <= self.config.tiny_active_threshold:
            self.stats.inc("tiny_active_iterations")
            self.stats.inc("fast_path_tiles", max(1, ceil(active_count / max(1, self.config.tiny_active_threshold))))
        else:
            self.stats.inc("full_path_iterations")
            self.stats.inc("full_path_tiles", self.config.num_partitions)

    def _finish(self) -> None:
        self._pending_result = {
            "reachable_vertices": len(self.dist),
            "max_distance": max(self.dist.values()) if self.dist else 0,
        }
        self.stats.set_value("reachable_vertices", self._pending_result["reachable_vertices"])
        self.stats.set_value("max_distance", self._pending_result["max_distance"])
        self.state = "emitting"


class HostDrain(Component):
    def __init__(self, input_fifo: FifoLink[dict[str, int]], stats: Stats) -> None:
        super().__init__("HostDrain")
        self.input_fifo = input_fifo
        self.stats = stats
        self.result: Optional[dict[str, int]] = None

    @property
    def done(self) -> bool:
        return self.result is not None

    def evaluate(self, cycle: int) -> None:
        del cycle
        if self.result is not None:
            return
        result = self.input_fifo.request_pop()
        if result is not None:
            self.result = result
            for key, value in result.items():
                self.stats.set_value(key, value)


class SpineV0Simulator:
    """Build and run the current Spine component graph."""

    def __init__(
        self, workload: Workload, config: SpineConfig, e2e_models: Any = None
    ) -> None:
        self.workload = workload
        self.config = config
        # Optional E2E bridge models (a spine_cycle_sim.calibration.bridge
        # BridgeModels bundle). When provided, ``_result`` attaches an ``"e2e"``
        # section (per-stage B/D_span/R + serial kernel + bottleneck) from the
        # HW-calibrated component models. Default None -> result unchanged,
        # preserving the prior "run() default behavior" contract.
        self.e2e_models = e2e_models
        self.stats = Stats()
        self.classification = classify_hot_cold(workload.edges, config)
        self.family_counts = self._family_counts(workload.edges)
        self.links: list[FifoLink[Any]] = []
        self.components: list[Component] = []
        self.hbm_partitions: list[HBMPartition] = []
        self.host: HostDrain | None = None
        self.level0: Level0Buffer | None = None
        self._build()

    def _new_fifo(self, name: str, depth: int | None = None) -> FifoLink[Any]:
        fifo: FifoLink[Any] = FifoLink(name, depth or self.config.fifo_depth, self.stats)
        self.links.append(fifo)
        return fifo

    def _build(self) -> None:
        edge_to_router = self._new_fifo("edge_to_router")
        router_to_l0 = [self._new_fifo(f"router_to_l0_f{f}") for f in range(self.config.family_count)]
        storage_events = self._new_fifo("level_to_carry")
        memory_fifos = [self._new_fifo(f"mem_req_bank{p}") for p in range(self.config.num_partitions)]
        sssp_start = self._new_fifo("sssp_start", 1)
        sssp_result = self._new_fifo("sssp_result", 1)

        edge_input = EdgeInput(
            self.workload.edges,
            edge_to_router,
            self.stats,
            self.config.edge_input_ii,
        )
        router = PartitionRouter(
            edge_to_router,
            router_to_l0,
            self.stats,
            self.config,
            self.classification.hot_dsts,
            self.config.router_ii,
        )
        router.upstream_done = lambda: edge_input.done

        level0 = Level0Buffer(
            router_to_l0,
            storage_events,
            self.stats,
            self.config,
            upstream_done=lambda: router.done,
            metadata_hot_enabled=self.config.hot_cold_enabled
            and not self.classification.empty_hot_set,
        )
        self.level0 = level0
        carry = Level1CarryMerge(
            storage_events,
            memory_fifos,
            self.stats,
            self.config,
            upstream_done=lambda: level0.done,
        )

        for partition, fifo in enumerate(memory_fifos):
            hbm = HBMPartition(
                name=f"HBMPartition[{partition}]",
                partition=partition,
                request_fifo=fifo,
                stats=self.stats,
                latency_cycles=self.config.hbm_latency_cycles,
                read_bw_edges_per_cycle=self.config.hbm_read_bw_edges_per_cycle,
                write_bw_edges_per_cycle=self.config.hbm_write_bw_edges_per_cycle,
                level_capacity_per_family=self.config.level_capacity_per_family,
            )
            self.hbm_partitions.append(hbm)

        storage_done = lambda: carry.done and all(hbm.idle for hbm in self.hbm_partitions)
        memory_idle = lambda: all(hbm.idle for hbm in self.hbm_partitions)
        readmaint = ReadMaintenance(
            memory_fifos,
            sssp_start,
            self.family_counts,
            self.workload.vertices,
            self.stats,
            self.config,
            storage_done=storage_done,
            memory_idle=memory_idle,
        )
        compute = SSSPCompute(
            sssp_start,
            sssp_result,
            self.workload.edges,
            self.workload.source,
            self.stats,
            self.config,
        )
        host = HostDrain(sssp_result, self.stats)
        self.host = host

        self.components = [
            edge_input,
            router,
            level0,
            carry,
            *self.hbm_partitions,
            readmaint,
            compute,
            host,
        ]

    def run(self, include_trace: bool = False) -> dict[str, Any]:
        simulator = CycleSimulator(
            self.components,
            self.links,
            self.stats,
            max_cycles=self.config.max_cycles,
        )
        cycles = simulator.run(lambda: self._done())
        return self._result(cycles, include_trace=include_trace)

    def _done(self) -> bool:
        return self.stats.failure is not None or (self.host is not None and self.host.done)

    def _family_for_edge(self, edge: Edge) -> int:
        if self.config.hot_cold_enabled and edge.dst in self.classification.hot_dsts:
            return self.config.hot_family_base + self.config.hot_shard_for_dst(edge.dst)
        return self.config.partition_for_dst(edge.dst)

    def _family_counts(self, edges: list[Edge]) -> list[int]:
        counts = [0 for _ in range(self.config.family_count)]
        for edge in edges:
            counts[self._family_for_edge(edge)] += 1
        return counts

    def _level_occupancy(self, level: int) -> list[int]:
        if self.level0 is None:
            return []
        return [self.level0.level_counts[family][level] for family in range(self.config.family_count)]

    def _all_level_occupancy(self) -> list[list[int]]:
        return [self._level_occupancy(level) for level in range(self.config.num_levels)]

    def _result(self, cycles: int, include_trace: bool = False) -> dict[str, Any]:
        freq_mhz = self.config.target_freq_mhz
        counters = self.stats.counters
        maintenance_estimated = int(counters.get("maintenance_estimated_cycles", 0))
        maintenance_scheduled = int(counters.get("maintenance_scheduled_cycles", 0))
        calibrated_extra = max(0, maintenance_estimated - maintenance_scheduled)
        calibrated_cycles = cycles + calibrated_extra
        time_ms = calibrated_cycles / (freq_mhz * 1000.0) if freq_mhz > 0 else 0.0
        edge_count = self.workload.edge_count
        eps = edge_count / (time_ms / 1000.0) if time_ms > 0 else 0.0
        failure = self.stats.failure
        level_occupancy = self._all_level_occupancy()
        tile_schedule = build_tile_schedule(
            self.workload.edges,
            self.workload.vertices,
            self.config,
        )
        maintenance_events = (
            [asdict(event) for event in self.level0.maintenance_events]
            if self.level0 is not None
            else []
        )
        result: dict[str, Any] = {
            "case": self.workload.metadata.get("case", self.workload.name),
            "workload": self.workload.name,
            "vertices": self.workload.vertices,
            "edges": edge_count,
            "source": self.workload.source,
            "config": asdict(self.config),
            "execution_cycles": cycles,
            "calibrated_extra_cycles": calibrated_extra,
            "cycles": calibrated_cycles,
            "calibrated_cycles": calibrated_cycles,
            "simulated_time_ms": time_ms,
            "edges_per_second": eps,
            "partition_load": list(self.classification.cold_partition_edges),
            "hot_shard_load": list(self.classification.hot_shard_edges),
            "family_load": list(self.family_counts),
            "level_occupancy": level_occupancy,
            "level0_occupancy": level_occupancy[0] if level_occupancy else [],
            "level1_occupancy": level_occupancy[1] if len(level_occupancy) > 1 else [],
            "carry_count": int(counters.get("carry_count", 0)),
            "cold_carry_count": int(counters.get("cold_carry_count", 0)),
            "hot_carry_count": int(counters.get("hot_carry_count", 0)),
            "maintenance_event_count": int(counters.get("maintenance_event_count", 0)),
            "maintenance_store_l0_events": int(counters.get("maintenance_store_l0_events", 0)),
            "maintenance_cascade_events": int(counters.get("maintenance_cascade_events", 0)),
            "maintenance_estimated_cycles": int(counters.get("maintenance_estimated_cycles", 0)),
            "maintenance_structural_estimated_cycles": int(
                counters.get("maintenance_structural_estimated_cycles", 0)
            ),
            "maintenance_calibrated_estimated_cycles": int(
                counters.get("maintenance_calibrated_estimated_cycles", 0)
            ),
            "maintenance_scheduled_cycles": int(counters.get("maintenance_scheduled_cycles", 0)),
            "maintenance_scan_passes": int(counters.get("maintenance_scan_passes", 0)),
            "maintenance_scan_cycles": int(counters.get("maintenance_scan_cycles", 0)),
            "maintenance_calibrated_scan_cycles": int(
                counters.get("maintenance_calibrated_scan_cycles", 0)
            ),
            "maintenance_cursor_read_cycles": int(counters.get("maintenance_cursor_read_cycles", 0)),
            "maintenance_bits_inspected": int(counters.get("maintenance_bits_inspected", 0)),
            "maintenance_payload_reads": int(counters.get("maintenance_payload_reads", 0)),
            "maintenance_refill_stalls": int(counters.get("maintenance_refill_stalls", 0)),
            "maintenance_merge_inputs": int(counters.get("maintenance_merge_inputs", 0)),
            "maintenance_outputs": int(counters.get("maintenance_outputs", 0)),
            "maintenance_page_ids_written": int(counters.get("maintenance_page_ids_written", 0)),
            "maintenance_max_target_level": int(
                self.stats.max_values.get("maintenance.max_target_level", 0)
            ),
            "target_selector_capacity_skips": int(
                counters.get("target_selector_capacity_skips", 0)
            ),
            "maintenance_events": maintenance_events,
            "hbm_request_count": int(counters.get("hbm_request_count", 0)),
            "fifo_stall_cycles": int(counters.get("fifo_stall_cycles", 0)),
            "memory_stall_cycles": int(counters.get("memory_stall_cycles", 0)),
            "compute_stall_cycles": int(counters.get("compute_stall_cycles", 0)),
            "sssp_iterations": int(counters.get("sssp_iterations", 0)),
            "tiny_active_iterations": int(counters.get("tiny_active_iterations", 0)),
            "full_path_iterations": int(counters.get("full_path_iterations", 0)),
            "fast_path_tiles": int(counters.get("fast_path_tiles", 0)),
            "full_path_tiles": int(counters.get("full_path_tiles", 0)),
            "dstage_tile_touched_tiles": tile_schedule.touched_tiles,
            "dstage_tile_marked_tiles": tile_schedule.marked_tiles,
            "dstage_tile_nonempty_tiles": tile_schedule.nonempty_tiles,
            "dstage_tile_empty_tile_passes": tile_schedule.empty_tile_passes,
            "dstage_tile_fallback_used": tile_schedule.fallback_used,
            "dstage_tile_row_lookups": tile_schedule.row_lookups,
            "dstage_tile_clipped_ranges": tile_schedule.clipped_ranges,
            "dstage_tile_active_record_replays": tile_schedule.active_record_replays,
            "dstage_tile_fast_path_tiles": tile_schedule.fast_path_tiles,
            "dstage_tile_full_path_tiles": tile_schedule.full_path_tiles,
            "dstage_tile_gathered_vertex_words": tile_schedule.gathered_vertex_words,
            "dstage_tile_swept_vertex_words": tile_schedule.swept_vertex_words,
            "dstage_tile_scattered_vertex_words": tile_schedule.scattered_vertex_words,
            "dstage_tile_active_records": tile_schedule.active_records,
            "dstage_tile_active_sources": tile_schedule.active_sources,
            "dstage_tile_traversed_edges": tile_schedule.traversed_edges,
            "dstage_tile_schedule": tile_schedule.to_dict()["entries"],
            "sssp_relax_attempts": int(counters.get("sssp_relax_attempts", 0)),
            "sssp_successful_relaxes": int(counters.get("sssp_successful_relaxes", 0)),
            "hot_enabled": not self.classification.empty_hot_set,
            "hot_edges": self.classification.hot_edges,
            "cold_edges": self.classification.cold_edges,
            "hot_vertex_count": self.classification.hot_vertex_count,
            "family_edge_capacity": self.classification.family_edge_cap,
            "capacity_status": "FAIL" if failure else "PASS",
            "capacity_failure": failure,
            "stats": self.stats.to_dict(include_trace=include_trace),
        }
        if self.e2e_models is not None:
            result["e2e"] = self._e2e_prediction(result)
        return result

    def _e2e_prediction(self, result: dict[str, Any]) -> dict[str, Any]:
        """Attach a per-stage E2E prediction via the calibration bridge.

        Imported lazily so the default simulator import stays free of the
        calibration/scripts layer; only runs when ``e2e_models`` is supplied.
        """

        from spine_cycle_sim.calibration.bridge import predict_e2e_from_results

        case = str(result.get("case", self.workload.name))
        sweep = str(self.workload.metadata.get("shape", "sim"))
        preds = predict_e2e_from_results(self.e2e_models, [(case, sweep, result)])
        return preds[0] if preds else {}
