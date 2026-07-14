"""Global cycle scheduler."""

from __future__ import annotations

from collections.abc import Callable, Sequence

from .component import Component
from .fifo import FifoLink
from .stats import Stats


class CycleSimulator:
    """Run a set of components and FIFO links with a global clock."""

    def __init__(
        self,
        components: Sequence[Component],
        links: Sequence[FifoLink[object]],
        stats: Stats,
        max_cycles: int,
    ) -> None:
        self.components = list(components)
        self.links = list(links)
        self.stats = stats
        self.max_cycles = max_cycles
        self.cycle = 0

    def run(self, done: Callable[[], bool]) -> int:
        while not done():
            if not self.tick():
                break
        self.stats.set_value("cycles", self.cycle)
        return self.cycle

    def tick(self) -> bool:
        """Advance the whole simulated hardware by one cycle."""

        if self.cycle >= self.max_cycles:
            self.stats.set_failure("max_cycles_exceeded", max_cycles=self.max_cycles)
            return False
        for component in self.components:
            component.evaluate(self.cycle)
        for component in self.components:
            component.commit(self.cycle)
        for link in self.links:
            link.commit()
        self.cycle += 1
        return True
