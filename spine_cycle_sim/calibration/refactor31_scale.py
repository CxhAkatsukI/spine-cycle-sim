"""Validation helpers for the routed refactor31 RMAT-24 scale matrix."""

from __future__ import annotations

import csv
from dataclasses import dataclass
import math
from pathlib import Path
import statistics
from typing import Any, Iterable


REQUIRED_FIELDS = (
    "graph",
    "graph_edges",
    "cohort",
    "state_class",
    "update_edges",
    "trial",
    "warmup",
    "processed_edges",
    "replay_payloads",
    "dispatch_status",
    "dispatch_cursor_mismatches",
    "ack_status",
    "task_error",
    "maintenance_ms",
    "reader_ms",
    "compute_ms",
    "convergence_ms",
    "e2e_ms",
    "errors",
)


@dataclass(frozen=True)
class Refactor31RmatRun:
    graph: str
    graph_edges: int
    cohort: str
    state_class: str
    update_edges: int
    trial: int
    warmup: bool
    processed_edges: int
    replay_payloads: int
    dispatch_status: int
    dispatch_cursor_mismatches: int
    ack_status: int
    task_error: int
    maintenance_ms: float
    reader_ms: float
    compute_ms: float
    convergence_ms: float
    e2e_ms: float
    errors: int

    @property
    def admitted(self) -> bool:
        return (
            self.graph == "raw_rmat24_9"
            and self.graph_edges == 150_994_944
            and self.processed_edges == self.replay_payloads
            and self.dispatch_status == 0
            and self.dispatch_cursor_mismatches == 0
            and self.ack_status == 0
            and self.task_error == 0
            and self.errors == 0
        )


def _integer(row: dict[str, str], field: str, source: str) -> int:
    try:
        return int(row[field], 0)
    except (KeyError, ValueError) as exc:
        raise ValueError(f"{source}: invalid integer field {field}") from exc


def _timing(row: dict[str, str], field: str, source: str) -> float:
    try:
        value = float(row[field])
    except (KeyError, ValueError) as exc:
        raise ValueError(f"{source}: invalid timing field {field}") from exc
    if not math.isfinite(value) or value < 0.0:
        raise ValueError(f"{source}: invalid timing field {field}={value}")
    return value


def load_refactor31_rmat_runs(path: str | Path) -> list[Refactor31RmatRun]:
    source_path = Path(path)
    records: list[Refactor31RmatRun] = []
    with source_path.open("r", encoding="utf-8", newline="") as handle:
        reader = csv.DictReader(handle)
        missing = [field for field in REQUIRED_FIELDS if field not in (reader.fieldnames or [])]
        if missing:
            raise ValueError(f"{source_path}: missing fields {','.join(missing)}")
        for line_number, row in enumerate(reader, start=2):
            source = f"{source_path}:{line_number}"
            record = Refactor31RmatRun(
                graph=row["graph"],
                graph_edges=_integer(row, "graph_edges", source),
                cohort=row["cohort"],
                state_class=row["state_class"],
                update_edges=_integer(row, "update_edges", source),
                trial=_integer(row, "trial", source),
                warmup=bool(_integer(row, "warmup", source)),
                processed_edges=_integer(row, "processed_edges", source),
                replay_payloads=_integer(row, "replay_payloads", source),
                dispatch_status=_integer(row, "dispatch_status", source),
                dispatch_cursor_mismatches=_integer(
                    row, "dispatch_cursor_mismatches", source
                ),
                ack_status=_integer(row, "ack_status", source),
                task_error=_integer(row, "task_error", source),
                maintenance_ms=_timing(row, "maintenance_ms", source),
                reader_ms=_timing(row, "reader_ms", source),
                compute_ms=_timing(row, "compute_ms", source),
                convergence_ms=_timing(row, "convergence_ms", source),
                e2e_ms=_timing(row, "e2e_ms", source),
                errors=_integer(row, "errors", source),
            )
            records.append(record)
    if not records:
        raise ValueError(f"{source_path}: empty RMAT evidence")
    return records


def validate_semantic_comparison(
    hashes_path: str | Path, mismatches_path: str | Path
) -> int:
    with Path(hashes_path).open("r", encoding="utf-8", newline="") as handle:
        rows = list(csv.DictReader(handle))
    if not rows:
        raise ValueError("semantic hash comparison is empty")
    for index, row in enumerate(rows, start=2):
        if (
            row.get("status") != "PASS"
            or row.get("baseline_sha256") != row.get("candidate_sha256")
        ):
            raise ValueError(f"semantic hash mismatch at row {index}")
    with Path(mismatches_path).open("r", encoding="utf-8", newline="") as handle:
        mismatches = list(csv.DictReader(handle))
    if mismatches:
        raise ValueError("semantic mismatch ledger is non-empty")
    return len(rows)


def summarize_refactor31_rmat_runs(
    records: Iterable[Refactor31RmatRun],
) -> list[dict[str, Any]]:
    grouped: dict[tuple[int, str, str], list[Refactor31RmatRun]] = {}
    for record in records:
        grouped.setdefault(
            (record.update_edges, record.cohort, record.state_class), []
        ).append(record)
    summaries: list[dict[str, Any]] = []
    for (update_edges, cohort, state_class), group in sorted(grouped.items()):
        measured = [record for record in group if not record.warmup]
        expected_measured = 40 if update_edges in (1, 16, 256) else 10
        expected_warmup = 2
        summaries.append(
            {
                "update_edges": update_edges,
                "cohort": cohort,
                "state_class": state_class,
                "rows": len(group),
                "measured_rows": len(measured),
                "warmup_rows": len(group) - len(measured),
                "admitted_rows": sum(record.admitted for record in group),
                "repeat_gate": int(
                    len(measured) == expected_measured
                    and len(group) - len(measured) == expected_warmup
                ),
                "semantic_ledger_gate": int(all(record.admitted for record in group)),
                "median_maintenance_ms": statistics.median(
                    record.maintenance_ms for record in measured
                ),
                "median_convergence_ms": statistics.median(
                    record.convergence_ms for record in measured
                ),
                "median_e2e_ms": statistics.median(
                    record.e2e_ms for record in measured
                ),
            }
        )
    return summaries
