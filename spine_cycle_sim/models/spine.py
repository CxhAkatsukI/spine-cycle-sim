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
    readmaintenance_vertex_scan_rate: int = 64
    tiny_active_threshold: int = 4096
    sssp_pipeline_ii: int = 1
    sssp_edges_per_cycle: int = 1

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
class StorageEvent:
    target_level: int
    family_base: int
    family_count: int
    counts_by_family: tuple[int, ...]
    edge_count: int
    carry: bool
    group: str
    tag: str


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
    ) -> None:
        super().__init__("Level0Buffer")
        self.inputs = inputs
        self.event_fifo = event_fifo
        self.stats = stats
        self.config = config
        self.upstream_done = upstream_done
        self.current_counts = [0 for _ in range(config.family_count)]
        self.level_counts = [
            [0 for _ in range(config.num_levels)] for _ in range(config.family_count)
        ]
        self.current_edges = 0
        self._pending_events: Deque[StorageEvent] = deque()
        self._rr_family = 0

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
            self.current_counts[family] += 1
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
        self._apply_group(0, self.config.num_partitions, "cold", tag)
        if self.config.hot_cold_enabled:
            self._apply_group(
                self.config.hot_family_base,
                self.config.hot_shards,
                "hot",
                tag,
            )
        self.current_counts = [0 for _ in range(self.config.family_count)]
        self.current_edges = 0

    def _apply_group(self, family_base: int, family_count: int, group: str, tag: str) -> None:
        group_input = sum(self.current_counts[family_base : family_base + family_count])
        if group_input == 0:
            return
        target = self._select_empty_target(family_base, family_count)
        if target < 0:
            self.stats.set_failure("level_exhausted", group=group)
            return
        combined = [0 for _ in range(self.config.family_count)]
        for family in range(family_base, family_base + family_count):
            count = self.current_counts[family]
            for level in range(target):
                count += self.level_counts[family][level]
            if count > self.config.level_family_capacity(target):
                self.stats.set_failure(
                    "level_family_capacity",
                    failure_level=target,
                    failure_family=family,
                    failure_partition=family % self.config.num_partitions,
                    failure_partition_edges=count,
                    failure_partition_capacity=self.config.level_family_capacity(target),
                    group=group,
                )
                return
            combined[family] = count

        for family in range(family_base, family_base + family_count):
            for level in range(target):
                self.level_counts[family][level] = 0
            self.level_counts[family][target] = combined[family]
            for level, value in enumerate(self.level_counts[family]):
                self.stats.max_value(f"family.{family}.level{level}.max_occupancy", value)

        edge_count = sum(combined)
        carry = target > 0
        if carry:
            self.stats.inc("carry_count")
            self.stats.inc(f"{group}_carry_count")
        self.stats.max_value(f"{group}.max_target_level", target)
        self.stats.max_value(f"level{target}.logical_occupancy.max", edge_count)
        self._pending_events.append(
            StorageEvent(
                target_level=target,
                family_base=family_base,
                family_count=family_count,
                counts_by_family=tuple(combined),
                edge_count=edge_count,
                carry=carry,
                group=group,
                tag=tag,
            )
        )

    def _select_empty_target(self, family_base: int, family_count: int) -> int:
        for level in range(self.config.num_levels):
            occupied = False
            for family in range(family_base, family_base + family_count):
                if self.level_counts[family][level] > 0:
                    occupied = True
                    break
            if not occupied:
                return level
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
            delay = ceil(event.edge_count / max(1, self.config.carry_merge_edges_per_cycle))
            self._ready_cycle = cycle + (delay if event.carry else 0)
            self.stats.add_trace(
                cycle,
                "carry_merge_accept_event",
                target_level=event.target_level,
                edge_count=event.edge_count,
                carry=event.carry,
                group=event.group,
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

    def __init__(self, workload: Workload, config: SpineConfig) -> None:
        self.workload = workload
        self.config = config
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
        time_ms = cycles / (freq_mhz * 1000.0) if freq_mhz > 0 else 0.0
        edge_count = self.workload.edge_count
        eps = edge_count / (time_ms / 1000.0) if time_ms > 0 else 0.0
        counters = self.stats.counters
        failure = self.stats.failure
        level_occupancy = self._all_level_occupancy()
        result: dict[str, Any] = {
            "case": self.workload.metadata.get("case", self.workload.name),
            "workload": self.workload.name,
            "vertices": self.workload.vertices,
            "edges": edge_count,
            "source": self.workload.source,
            "config": asdict(self.config),
            "cycles": cycles,
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
            "hbm_request_count": int(counters.get("hbm_request_count", 0)),
            "fifo_stall_cycles": int(counters.get("fifo_stall_cycles", 0)),
            "memory_stall_cycles": int(counters.get("memory_stall_cycles", 0)),
            "compute_stall_cycles": int(counters.get("compute_stall_cycles", 0)),
            "sssp_iterations": int(counters.get("sssp_iterations", 0)),
            "tiny_active_iterations": int(counters.get("tiny_active_iterations", 0)),
            "full_path_iterations": int(counters.get("full_path_iterations", 0)),
            "fast_path_tiles": int(counters.get("fast_path_tiles", 0)),
            "full_path_tiles": int(counters.get("full_path_tiles", 0)),
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
        return result
