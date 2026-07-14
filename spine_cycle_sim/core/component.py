"""Base component interface for the two-phase simulator."""

from __future__ import annotations


class Component:
    """A clocked simulator component.

    Components observe stable state in ``evaluate`` and publish state changes in
    ``commit``. FIFO/link commits happen after component commits, so data pushed
    by one component becomes visible to downstream components on the next cycle.
    """

    def __init__(self, name: str) -> None:
        self.name = name

    def evaluate(self, cycle: int) -> None:
        del cycle

    def commit(self, cycle: int) -> None:
        del cycle

    @property
    def done(self) -> bool:
        return True
