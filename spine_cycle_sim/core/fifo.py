"""Finite-capacity links used between simulator components."""

from __future__ import annotations

from collections import deque
from typing import Deque, Generic, Iterable, Optional, TypeVar

from .stats import Stats

T = TypeVar("T")


class FifoLink(Generic[T]):
    """A single-reader, single-writer FIFO with two-phase updates."""

    def __init__(self, name: str, depth: int, stats: Optional[Stats] = None) -> None:
        if depth <= 0:
            raise ValueError(f"FIFO {name} depth must be positive")
        self.name = name
        self.depth = depth
        self._items: Deque[T] = deque()
        self._push_next: list[T] = []
        self._pop_next = 0
        self._stats = stats

    def __len__(self) -> int:
        return len(self._items)

    def items(self) -> Iterable[T]:
        return tuple(self._items)

    @property
    def empty(self) -> bool:
        return not self._items and not self._push_next

    @property
    def full(self) -> bool:
        return len(self._items) + len(self._push_next) >= self.depth

    def can_push(self) -> bool:
        return len(self._items) + len(self._push_next) < self.depth

    def request_push(self, item: T) -> bool:
        if not self.can_push():
            if self._stats is not None:
                self._stats.inc("fifo_stall_cycles")
                self._stats.inc(f"fifo.{self.name}.push_stall_cycles")
            return False
        self._push_next.append(item)
        return True

    def can_pop(self) -> bool:
        return bool(self._items) and self._pop_next == 0

    def peek(self) -> Optional[T]:
        if not self.can_pop():
            return None
        return self._items[0]

    def request_pop(self) -> Optional[T]:
        if not self.can_pop():
            return None
        self._pop_next = 1
        return self._items[0]

    def commit(self) -> None:
        for _ in range(self._pop_next):
            self._items.popleft()
        self._items.extend(self._push_next)
        self._pop_next = 0
        self._push_next = []
        if self._stats is not None:
            self._stats.max_value(f"fifo.{self.name}.max_occupancy", len(self._items))
