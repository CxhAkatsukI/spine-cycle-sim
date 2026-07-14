"""Statistics collection for simulator runs."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class Stats:
    counters: dict[str, int | float] = field(default_factory=dict)
    values: dict[str, Any] = field(default_factory=dict)
    max_values: dict[str, int | float] = field(default_factory=dict)
    trace: list[dict[str, Any]] = field(default_factory=list)
    failure: dict[str, Any] | None = None

    def inc(self, key: str, amount: int | float = 1) -> None:
        self.counters[key] = self.counters.get(key, 0) + amount

    def set_value(self, key: str, value: Any) -> None:
        self.values[key] = value

    def max_value(self, key: str, value: int | float) -> None:
        current = self.max_values.get(key)
        if current is None or value > current:
            self.max_values[key] = value

    def add_trace(self, cycle: int, event: str, **fields: Any) -> None:
        record = {"cycle": cycle, "event": event}
        record.update(fields)
        self.trace.append(record)

    def set_failure(self, reason: str, **fields: Any) -> None:
        if self.failure is None:
            self.failure = {"reason": reason}
            self.failure.update(fields)

    def to_dict(self, include_trace: bool = False) -> dict[str, Any]:
        data: dict[str, Any] = {
            "counters": dict(sorted(self.counters.items())),
            "values": dict(sorted(self.values.items())),
            "max_values": dict(sorted(self.max_values.items())),
            "failure": self.failure,
        }
        if include_trace:
            data["trace"] = list(self.trace)
        return data
