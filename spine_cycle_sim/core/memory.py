"""Simple HBM partition model."""

from __future__ import annotations

from dataclasses import dataclass
from math import ceil
from typing import Optional

from .component import Component
from .fifo import FifoLink
from .stats import Stats


@dataclass(frozen=True)
class MemoryRequest:
    partition: int
    family: int
    op: str
    level: int
    edge_count: int
    mode: str = "replace"
    clear_lower: bool = False
    tag: str = ""


@dataclass
class _ActiveRequest:
    request: MemoryRequest
    done_cycle: int


class HBMPartition(Component):
    """A coarse HBM bank model with one outstanding request per partition."""

    def __init__(
        self,
        name: str,
        partition: int,
        request_fifo: FifoLink[MemoryRequest],
        stats: Stats,
        latency_cycles: int,
        read_bw_edges_per_cycle: int,
        write_bw_edges_per_cycle: int,
        level_capacity_per_family: dict[int, int],
    ) -> None:
        super().__init__(name)
        self.partition = partition
        self.request_fifo = request_fifo
        self.stats = stats
        self.latency_cycles = latency_cycles
        self.read_bw_edges_per_cycle = max(1, read_bw_edges_per_cycle)
        self.write_bw_edges_per_cycle = max(1, write_bw_edges_per_cycle)
        self.level_capacity_per_family = dict(level_capacity_per_family)
        self.occupancy_by_family_level: dict[tuple[int, int], int] = {}
        self._active: Optional[_ActiveRequest] = None
        self._accepted: Optional[MemoryRequest] = None
        self._completed: Optional[MemoryRequest] = None

    @property
    def idle(self) -> bool:
        return self._active is None and self.request_fifo.empty

    def evaluate(self, cycle: int) -> None:
        self._accepted = None
        self._completed = None
        if self._active is not None:
            self.stats.inc("memory_stall_cycles")
            self.stats.inc(f"hbm.partition{self.partition}.busy_cycles")
            if cycle >= self._active.done_cycle:
                self._completed = self._active.request
            return

        request = self.request_fifo.request_pop()
        if request is None:
            return
        self._accepted = request

    def commit(self, cycle: int) -> None:
        if self._completed is not None:
            request = self._completed
            if request.op == "write":
                cap = self.level_capacity_per_family.get(request.level)
                if cap is not None and request.edge_count > cap:
                    self.stats.set_failure(
                        "level_family_capacity",
                        failure_level=request.level,
                        failure_partition=self.partition,
                        failure_family=request.family,
                        failure_partition_edges=request.edge_count,
                        failure_partition_capacity=cap,
                    )
                if request.clear_lower:
                    for family, level in list(self.occupancy_by_family_level):
                        if family == request.family and level < request.level:
                            self.occupancy_by_family_level[(family, level)] = 0
                key = (request.family, request.level)
                if request.mode == "append":
                    self.occupancy_by_family_level[key] = (
                        self.occupancy_by_family_level.get(key, 0) + request.edge_count
                    )
                else:
                    self.occupancy_by_family_level[key] = request.edge_count
                self.stats.max_value(
                    f"hbm.partition{self.partition}.family{request.family}.level{request.level}.max_occupancy",
                    self.occupancy_by_family_level[key],
                )
            self.stats.add_trace(
                cycle,
                "hbm_complete",
                partition=self.partition,
                family=request.family,
                op=request.op,
                level=request.level,
                edge_count=request.edge_count,
                tag=request.tag,
            )
            self._active = None

        if self._accepted is not None and self._active is None:
            request = self._accepted
            bw = self.read_bw_edges_per_cycle if request.op == "read" else self.write_bw_edges_per_cycle
            service_cycles = max(1, ceil(max(1, request.edge_count) / bw))
            self._active = _ActiveRequest(
                request=request,
                done_cycle=cycle + self.latency_cycles + service_cycles,
            )
            self.stats.inc("hbm_request_count")
            self.stats.inc(f"hbm_{request.op}_request_count")
            self.stats.inc("hbm_edge_traffic", request.edge_count)
            self.stats.inc(f"hbm_{request.op}_edge_traffic", request.edge_count)
            self.stats.add_trace(
                cycle,
                "hbm_accept",
                partition=self.partition,
                family=request.family,
                op=request.op,
                level=request.level,
                edge_count=request.edge_count,
                tag=request.tag,
            )

    @property
    def done(self) -> bool:
        return self.idle
