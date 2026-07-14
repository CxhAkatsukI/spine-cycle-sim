"""Spine v0 cycle-level architecture model."""

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
    num_partitions: int = 16
    target_freq_mhz: float = 150.0
    fifo_depth: int = 32
    max_cycles: int = 10_000_000
    edge_input_ii: int = 1
    router_ii: int = 1
    level0_accept_edges_per_cycle: int = 16
    batch_size_edges: int = 131_072
    level0_capacity_per_partition: int = 131_072
    level1_capacity_total: int = 262_144
    level1_capacity_per_partition: int = 16_384
    carry_merge_edges_per_cycle: int = 16
    hbm_latency_cycles: int = 200
    hbm_read_bw_edges_per_cycle: int = 16
    hbm_write_bw_edges_per_cycle: int = 16
    readmaintenance_vertex_scan_rate: int = 64
    sssp_pipeline_ii: int = 1
    sssp_edges_per_cycle: int = 1

    @property
    def level_capacity_per_partition(self) -> dict[int, int]:
        return {
            0: self.level0_capacity_per_partition,
            1: self.level1_capacity_per_partition,
        }

    @property
    def level_capacity_total(self) -> dict[int, int]:
        return {
            0: self.level0_capacity_per_partition * self.num_partitions,
            1: self.level1_capacity_total,
        }


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


@dataclass(frozen=True)
class EdgePacket:
    edge: Edge
    sequence: int
    partition: int = -1


@dataclass(frozen=True)
class StorageEvent:
    target_level: int
    counts_by_partition: tuple[int, ...]
    edge_count: int
    carry: bool
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
        if self.done:
            return
        if cycle < self.next_emit_cycle:
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
        router_ii: int,
    ) -> None:
        super().__init__("PartitionRouter")
        self.input_fifo = input_fifo
        self.outputs = outputs
        self.stats = stats
        self.router_ii = max(1, router_ii)
        self.next_route_cycle = 0
        self.upstream_done: Callable[[], bool] = lambda: False

    @property
    def done(self) -> bool:
        return self.upstream_done() and self.input_fifo.empty

    def evaluate(self, cycle: int) -> None:
        if cycle < self.next_route_cycle:
            return
        packet = self.input_fifo.peek()
        if packet is None:
            return
        partition = packet.edge.dst % len(self.outputs)
        output = self.outputs[partition]
        if not output.can_push():
            self.stats.inc("router_output_stall_cycles")
            return
        popped = self.input_fifo.request_pop()
        if popped is None:
            return
        output.request_push(EdgePacket(popped.edge, popped.sequence, partition))
        self.stats.inc("router_routed_edges")
        self.stats.inc(f"partition.{partition}.routed_edges")
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
        self.current_counts = [0 for _ in range(config.num_partitions)]
        self.l0_counts = [0 for _ in range(config.num_partitions)]
        self.current_edges = 0
        self.l0_edges = 0
        self._pending_event: Optional[StorageEvent] = None
        self._rr_partition = 0

    @property
    def done(self) -> bool:
        return (
            self.upstream_done()
            and all(fifo.empty for fifo in self.inputs)
            and self.current_edges == 0
            and self._pending_event is None
        )

    def evaluate(self, cycle: int) -> None:
        if self._pending_event is not None:
            if self.event_fifo.request_push(self._pending_event):
                self.stats.add_trace(
                    cycle,
                    "level0_emit_storage_event",
                    target_level=self._pending_event.target_level,
                    edge_count=self._pending_event.edge_count,
                    carry=self._pending_event.carry,
                )
                self._pending_event = None
            return

        accepted = 0
        budget = max(1, self.config.level0_accept_edges_per_cycle)
        for offset in range(self.config.num_partitions):
            if accepted >= budget:
                break
            partition = (self._rr_partition + offset) % self.config.num_partitions
            packet = self.inputs[partition].request_pop()
            if packet is None:
                continue
            self.current_counts[partition] += 1
            self.current_edges += 1
            accepted += 1
            self.stats.inc("level0_accepted_edges")
            self.stats.max_value("level0.current_batch_edges.max", self.current_edges)
            if self.current_edges >= self.config.batch_size_edges:
                self._prepare_flush("full_batch")
                break
        self._rr_partition = (self._rr_partition + 1) % self.config.num_partitions

        if (
            self._pending_event is None
            and self.current_edges > 0
            and self.upstream_done()
            and all(fifo.empty for fifo in self.inputs)
        ):
            self._prepare_flush("final_batch")

    def _prepare_flush(self, tag: str) -> None:
        if self.l0_edges == 0:
            counts = tuple(self.current_counts)
            self._pending_event = StorageEvent(
                target_level=0,
                counts_by_partition=counts,
                edge_count=self.current_edges,
                carry=False,
                tag=tag,
            )
            self.l0_counts = list(self.current_counts)
            self.l0_edges = self.current_edges
            self.stats.max_value("level0.logical_occupancy.max", self.l0_edges)
        else:
            counts = tuple(a + b for a, b in zip(self.l0_counts, self.current_counts))
            edge_count = self.l0_edges + self.current_edges
            self._pending_event = StorageEvent(
                target_level=1,
                counts_by_partition=counts,
                edge_count=edge_count,
                carry=True,
                tag=tag,
            )
            self.l0_counts = [0 for _ in range(self.config.num_partitions)]
            self.l0_edges = 0
            self.stats.max_value("level1.logical_occupancy.max", edge_count)
        self.current_counts = [0 for _ in range(self.config.num_partitions)]
        self.current_edges = 0


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
        self._partition_index = 0

    @property
    def done(self) -> bool:
        return self.upstream_done() and self.input_fifo.empty and self._event is None

    def evaluate(self, cycle: int) -> None:
        if self._event is None:
            event = self.input_fifo.request_pop()
            if event is None:
                return
            self._event = event
            self._partition_index = 0
            delay = 0
            if event.carry:
                self.stats.inc("carry_count")
                delay = ceil(event.edge_count / max(1, self.config.carry_merge_edges_per_cycle))
            self._ready_cycle = cycle + delay
            self._check_capacity(event)
            self.stats.add_trace(
                cycle,
                "carry_merge_accept_event",
                target_level=event.target_level,
                edge_count=event.edge_count,
                carry=event.carry,
            )
            return

        if cycle < self._ready_cycle:
            self.stats.inc("carry_merge_busy_cycles")
            return

        while self._event is not None and self._partition_index < self.config.num_partitions:
            partition = self._partition_index
            count = self._event.counts_by_partition[partition]
            must_clear = self._event.target_level > 0
            if count == 0 and not must_clear:
                self._partition_index += 1
                continue
            request = MemoryRequest(
                partition=partition,
                op="write",
                level=self._event.target_level,
                edge_count=count,
                mode="replace",
                clear_lower=must_clear,
                tag=self._event.tag,
            )
            if not self.memory_fifos[partition].request_push(request):
                self.stats.inc("carry_merge_memory_output_stall_cycles")
                return
            self._partition_index += 1
        if self._event is not None and self._partition_index >= self.config.num_partitions:
            self.stats.add_trace(
                cycle,
                "carry_merge_emit_memory_requests",
                target_level=self._event.target_level,
                edge_count=self._event.edge_count,
            )
            self._event = None

    def _check_capacity(self, event: StorageEvent) -> None:
        total_cap = self.config.level_capacity_total.get(event.target_level)
        if total_cap is not None and event.edge_count > total_cap:
            self.stats.set_failure(
                "level_total_capacity",
                failure_level=event.target_level,
                failure_edges=event.edge_count,
                failure_capacity=total_cap,
            )
            return
        part_cap = self.config.level_capacity_per_partition.get(event.target_level)
        if part_cap is None:
            return
        for partition, count in enumerate(event.counts_by_partition):
            if count > part_cap:
                self.stats.set_failure(
                    "level_partition_capacity",
                    failure_level=event.target_level,
                    failure_partition=partition,
                    failure_partition_edges=count,
                    failure_partition_capacity=part_cap,
                )
                return


class ReadMaintenance(Component):
    def __init__(
        self,
        memory_fifos: list[FifoLink[MemoryRequest]],
        start_fifo: FifoLink[dict[str, int]],
        partition_counts: list[int],
        vertices: int,
        stats: Stats,
        config: SpineConfig,
        storage_done: Callable[[], bool],
        memory_idle: Callable[[], bool],
    ) -> None:
        super().__init__("ReadMaintenance")
        self.memory_fifos = memory_fifos
        self.start_fifo = start_fifo
        self.partition_counts = partition_counts
        self.vertices = vertices
        self.stats = stats
        self.config = config
        self.storage_done = storage_done
        self.memory_idle = memory_idle
        self.state = "waiting"
        self.scan_done_cycle = 0
        self.partition_index = 0

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
            while self.partition_index < self.config.num_partitions:
                count = self.partition_counts[self.partition_index]
                if count == 0:
                    self.partition_index += 1
                    continue
                request = MemoryRequest(
                    partition=self.partition_index,
                    op="read",
                    level=0,
                    edge_count=count,
                    tag="readmaintenance",
                )
                if not self.memory_fifos[self.partition_index].request_push(request):
                    self.stats.inc("readmaintenance_memory_output_stall_cycles")
                    return
                self.partition_index += 1
            self.state = "waiting_reads"
            return
        if self.state == "waiting_reads":
            if self.memory_idle():
                if self.start_fifo.request_push({"edge_count": sum(self.partition_counts)}):
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
                    self.rounds += 1
                    self.stats.inc("sssp_iterations")
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
        self.rounds = 1
        self.stats.inc("sssp_iterations")
        self.next_compute_cycle = cycle
        self.stats.add_trace(cycle, "sssp_start", source=self.source)

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
    """Build and run the Spine v0 component graph."""

    def __init__(self, workload: Workload, config: SpineConfig) -> None:
        self.workload = workload
        self.config = config
        self.stats = Stats()
        self.partition_counts = self._partition_counts(workload.edges)
        self.links: list[FifoLink[Any]] = []
        self.components: list[Component] = []
        self.hbm_partitions: list[HBMPartition] = []
        self.host: HostDrain | None = None
        self._build()

    def _new_fifo(self, name: str, depth: int | None = None) -> FifoLink[Any]:
        fifo: FifoLink[Any] = FifoLink(name, depth or self.config.fifo_depth, self.stats)
        self.links.append(fifo)
        return fifo

    def _build(self) -> None:
        edge_to_router = self._new_fifo("edge_to_router")
        router_to_l0 = [self._new_fifo(f"router_to_l0_p{p}") for p in range(self.config.num_partitions)]
        storage_events = self._new_fifo("level0_to_carry")
        memory_fifos = [self._new_fifo(f"mem_req_p{p}") for p in range(self.config.num_partitions)]
        sssp_start = self._new_fifo("sssp_start", 1)
        sssp_result = self._new_fifo("sssp_result", 1)

        edge_input = EdgeInput(
            self.workload.edges,
            edge_to_router,
            self.stats,
            self.config.edge_input_ii,
        )
        router = PartitionRouter(edge_to_router, router_to_l0, self.stats, self.config.router_ii)
        router.upstream_done = lambda: edge_input.done

        level0 = Level0Buffer(
            router_to_l0,
            storage_events,
            self.stats,
            self.config,
            upstream_done=lambda: router.done,
        )
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
                level_capacity_per_partition=self.config.level_capacity_per_partition,
            )
            self.hbm_partitions.append(hbm)

        storage_done = lambda: carry.done and all(hbm.idle for hbm in self.hbm_partitions)
        memory_idle = lambda: all(hbm.idle for hbm in self.hbm_partitions)
        readmaint = ReadMaintenance(
            memory_fifos,
            sssp_start,
            self.partition_counts,
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

    def _partition_counts(self, edges: list[Edge]) -> list[int]:
        counts = [0 for _ in range(self.config.num_partitions)]
        for edge in edges:
            counts[edge.dst % self.config.num_partitions] += 1
        return counts

    def _occupancy(self, level: int) -> list[int]:
        return [hbm.occupancy_by_level.get(level, 0) for hbm in self.hbm_partitions]

    def _result(self, cycles: int, include_trace: bool = False) -> dict[str, Any]:
        freq_mhz = self.config.target_freq_mhz
        time_ms = cycles / (freq_mhz * 1000.0) if freq_mhz > 0 else 0.0
        edge_count = self.workload.edge_count
        eps = edge_count / (time_ms / 1000.0) if time_ms > 0 else 0.0
        counters = self.stats.counters
        failure = self.stats.failure
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
            "partition_load": list(self.partition_counts),
            "level0_occupancy": self._occupancy(0),
            "level1_occupancy": self._occupancy(1),
            "carry_count": int(counters.get("carry_count", 0)),
            "hbm_request_count": int(counters.get("hbm_request_count", 0)),
            "fifo_stall_cycles": int(counters.get("fifo_stall_cycles", 0)),
            "memory_stall_cycles": int(counters.get("memory_stall_cycles", 0)),
            "compute_stall_cycles": int(counters.get("compute_stall_cycles", 0)),
            "sssp_iterations": int(counters.get("sssp_iterations", 0)),
            "sssp_relax_attempts": int(counters.get("sssp_relax_attempts", 0)),
            "sssp_successful_relaxes": int(counters.get("sssp_successful_relaxes", 0)),
            "capacity_status": "FAIL" if failure else "PASS",
            "capacity_failure": failure,
            "stats": self.stats.to_dict(include_trace=include_trace),
        }
        return result
