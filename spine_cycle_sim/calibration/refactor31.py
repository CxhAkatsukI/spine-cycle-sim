"""Hash-bound timing evidence from the routed refactor31 Spine artifact."""

from __future__ import annotations

from dataclasses import asdict, dataclass
import math
from pathlib import Path
import re
import statistics
from typing import Any, Iterable


KEY_VALUE_RE = re.compile(r"([A-Za-z_][A-Za-z0-9_]*)=([^\s]+)")
LINE_PREFIX = "SEGMENTED_FALLBACK_HW "
TIMING_FIELDS = ("reader_ms", "compute_ms", "conv_ms", "wall_ms")


@dataclass(frozen=True)
class Refactor31FPGARun:
    source_log: str
    status: str
    case: str
    launch: int
    phase: str
    reference_validated: bool
    vertices: int
    edges: int
    active_sources: int
    active_records: int
    next_active: int
    processed: int
    path: int
    fallback: bool
    task_error: int
    errors: int
    clock_mhz: float
    reader_ms: float
    compute_ms: float
    conv_ms: float
    wall_ms: float

    @property
    def timing_admitted(self) -> bool:
        return (
            self.status == "PASS"
            and self.errors == 0
            and self.task_error == 0
            and self.processed == self.edges
        )

    @property
    def correctness_admitted(self) -> bool:
        return self.timing_admitted and self.reference_validated

    def cycles(self, timing_field: str) -> int:
        if timing_field not in TIMING_FIELDS:
            raise KeyError(f"unknown refactor31 timing field: {timing_field}")
        return round(float(getattr(self, timing_field)) * self.clock_mhz * 1000.0)

    @property
    def reader_cycles(self) -> int:
        return self.cycles("reader_ms")

    @property
    def compute_cycles(self) -> int:
        return self.cycles("compute_ms")

    @property
    def conv_cycles(self) -> int:
        return self.cycles("conv_ms")

    @property
    def wall_cycles(self) -> int:
        return self.cycles("wall_ms")

    def to_row(self) -> dict[str, Any]:
        row = asdict(self)
        row["reference_validated"] = int(self.reference_validated)
        row["fallback"] = int(self.fallback)
        row["timing_admitted"] = int(self.timing_admitted)
        row["correctness_admitted"] = int(self.correctness_admitted)
        for field in TIMING_FIELDS:
            row[field.removesuffix("_ms") + "_cycles"] = self.cycles(field)
        return row


def _required(fields: dict[str, str], field: str, source: str) -> str:
    if field not in fields:
        raise ValueError(f"{source}: refactor31 result is missing {field}")
    return fields[field]


def _integer(fields: dict[str, str], field: str, source: str) -> int:
    try:
        return int(_required(fields, field, source), 0)
    except ValueError as exc:
        raise ValueError(f"{source}: invalid integer {field}") from exc


def _timing(fields: dict[str, str], field: str, source: str) -> float:
    try:
        value = float(_required(fields, field, source))
    except ValueError as exc:
        raise ValueError(f"{source}: invalid timing {field}") from exc
    if not math.isfinite(value) or value < 0:
        raise ValueError(f"{source}: invalid timing {field}={value}")
    return value


def parse_refactor31_fpga_log(
    text: str,
    *,
    source_log: str = "<memory>",
    clock_mhz: float = 160.0,
) -> list[Refactor31FPGARun]:
    """Parse every structured launch result from one direct-FPGA log."""

    if not math.isfinite(clock_mhz) or clock_mhz <= 0:
        raise ValueError("clock_mhz must be positive and finite")
    records: list[Refactor31FPGARun] = []
    for line_number, raw_line in enumerate(text.splitlines(), start=1):
        line = raw_line.strip()
        if not line.startswith(LINE_PREFIX):
            continue
        tokens = line.split(None, 2)
        if len(tokens) < 3:
            raise ValueError(f"{source_log}:{line_number}: malformed result line")
        status = tokens[1]
        fields = dict(KEY_VALUE_RE.findall(tokens[2]))
        source = f"{source_log}:{line_number}"
        records.append(
            Refactor31FPGARun(
                source_log=source_log,
                status=status,
                case=_required(fields, "case", source),
                launch=_integer(fields, "launch", source),
                phase=_required(fields, "phase", source),
                reference_validated=bool(
                    _integer(fields, "reference_validated", source)
                ),
                vertices=_integer(fields, "vertices", source),
                edges=_integer(fields, "edges", source),
                active_sources=_integer(fields, "active_sources", source),
                active_records=_integer(fields, "active_records", source),
                next_active=_integer(fields, "next_active", source),
                processed=_integer(fields, "processed", source),
                path=_integer(fields, "path", source),
                fallback=bool(_integer(fields, "fallback", source)),
                task_error=_integer(fields, "task_error", source),
                errors=_integer(fields, "errors", source),
                clock_mhz=float(clock_mhz),
                reader_ms=_timing(fields, "reader_ms", source),
                compute_ms=_timing(fields, "compute_ms", source),
                conv_ms=_timing(fields, "conv_ms", source),
                wall_ms=_timing(fields, "wall_ms", source),
            )
        )
    if not records:
        raise ValueError(f"{source_log}: no {LINE_PREFIX.strip()} records")
    return records


def load_refactor31_fpga_logs(
    paths: Iterable[str | Path], *, clock_mhz: float = 160.0
) -> list[Refactor31FPGARun]:
    records: list[Refactor31FPGARun] = []
    for path_value in paths:
        path = Path(path_value).resolve()
        records.extend(
            parse_refactor31_fpga_log(
                path.read_text(encoding="utf-8", errors="replace"),
                source_log=str(path),
                clock_mhz=clock_mhz,
            )
        )
    return records


def _cv_pct(values: list[float]) -> float:
    if len(values) < 2:
        return 0.0
    mean = statistics.fmean(values)
    return 0.0 if mean == 0 else statistics.pstdev(values) / mean * 100.0


def summarize_refactor31_fpga_runs(
    records: Iterable[Refactor31FPGARun], *, required_repeats: int = 5
) -> list[dict[str, Any]]:
    """Aggregate launches without upgrading stability evidence to correctness."""

    if required_repeats <= 0:
        raise ValueError("required_repeats must be positive")
    grouped: dict[str, list[Refactor31FPGARun]] = {}
    for record in records:
        grouped.setdefault(record.case, []).append(record)

    rows: list[dict[str, Any]] = []
    for case in sorted(grouped):
        case_records = sorted(grouped[case], key=lambda record: record.launch)
        timing_records = [record for record in case_records if record.timing_admitted]
        correctness_records = [
            record for record in case_records if record.correctness_admitted
        ]
        shape_fields = (
            "vertices",
            "edges",
            "active_sources",
            "active_records",
            "path",
            "fallback",
        )
        shape_consistent = all(
            getattr(record, field) == getattr(case_records[0], field)
            for record in case_records[1:]
            for field in shape_fields
        )
        row: dict[str, Any] = {
            "case": case,
            "samples": len(case_records),
            "timing_admitted_samples": len(timing_records),
            "correctness_admitted_samples": len(correctness_records),
            "required_repeats": required_repeats,
            "shape_consistent": int(shape_consistent),
            "repeat_gate": int(len(timing_records) >= required_repeats),
            "correctness_gate": int(
                len(correctness_records) >= required_repeats
            ),
            "timing_baseline_scope": (
                "timing_stability_only"
                if timing_records and not correctness_records
                else "correctness_admitted"
                if correctness_records
                else "rejected"
            ),
        }
        for field in shape_fields:
            row[field] = int(getattr(case_records[0], field))
        for field in TIMING_FIELDS:
            milliseconds = [float(getattr(record, field)) for record in timing_records]
            cycles = [float(record.cycles(field)) for record in timing_records]
            prefix = field.removesuffix("_ms")
            row[f"median_{field}"] = (
                statistics.median(milliseconds) if milliseconds else math.nan
            )
            row[f"median_{prefix}_cycles"] = (
                round(statistics.median(cycles)) if cycles else ""
            )
            row[f"{prefix}_cv_pct"] = _cv_pct(milliseconds)
        row["calibration_admitted"] = int(
            bool(shape_consistent)
            and bool(row["repeat_gate"])
            and bool(row["correctness_gate"])
        )
        rows.append(row)
    return rows
