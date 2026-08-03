"""Hash-bound timing evidence from the routed refactor31 Spine artifact."""

from __future__ import annotations

from dataclasses import asdict, dataclass
import json
import math
from pathlib import Path
import re
import statistics
from typing import Any, Iterable


REFACTOR31_VERTICES = 1_048_576
REFACTOR31_ACTIVE_GATE = 16_384
REFACTOR31_CASES = (
    "active_exact_one_tile",
    "active_gate_one_tile",
    "active_exact_many_tiles",
    "active_gate_many_tiles",
)


KEY_VALUE_RE = re.compile(r"([A-Za-z_][A-Za-z0-9_]*)=([^\s]+)")
LINE_PREFIX = "SEGMENTED_FALLBACK_HW "
REAL_SLICE_LINE_PREFIX = "REFACTOR31_REAL_SLICE_HW "
TIMING_FIELDS = ("reader_ms", "compute_ms", "conv_ms", "wall_ms")


def refactor31_fixture_edges(case: str) -> list[tuple[int, int, int, int]]:
    """Reproduce the four accepted direct-FPGA host fixtures."""

    if case not in REFACTOR31_CASES:
        raise ValueError(f"unknown refactor31 fixture: {case}")
    count = REFACTOR31_ACTIVE_GATE + ("_gate_" in case)
    many_tiles = case.endswith("many_tiles")
    edges: list[tuple[int, int, int, int]] = []
    for index in range(count):
        if many_tiles:
            source = REFACTOR31_VERTICES - 1 - index
            destination = index * REFACTOR31_VERTICES // count
        else:
            source = 65_536 + index
            destination = index % 65_536
        edges.append((source, destination, 1, 1))
    return sorted(edges, key=lambda edge: (edge[0], edge[1]))


def write_refactor31_fixture(path: str | Path, case: str) -> Path:
    output = Path(path)
    output.parent.mkdir(parents=True, exist_ok=True)
    with output.open("w", encoding="ascii") as stream:
        stream.write("# spine_real_slice_version=1\n")
        stream.write(f"# case={case}\n")
        stream.write(f"# vertices={REFACTOR31_VERTICES}\n")
        stream.write("# columns=src dst weight diff\n")
        for edge in refactor31_fixture_edges(case):
            stream.write("{} {} {} {}\n".format(*edge))
    return output


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


@dataclass(frozen=True)
class Refactor31RealSliceFPGARun:
    source_log: str
    status: str
    slice: str
    source: int
    vertices: int
    graph_edges: int
    resident_level: int
    rounds: int
    processed_edges: int
    reader_cycles: int
    compute_cycles: int
    paired_cycles: int
    dijkstra_mismatches: int
    reference_validated: bool
    errors: int

    @property
    def correctness_admitted(self) -> bool:
        return (
            self.status == "PASS"
            and self.rounds > 0
            and self.errors == 0
            and self.dijkstra_mismatches == 0
            and self.reference_validated
        )

    def to_row(self) -> dict[str, Any]:
        row = asdict(self)
        row["reference_validated"] = int(self.reference_validated)
        row["correctness_admitted"] = int(self.correctness_admitted)
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


def parse_refactor31_real_slice_fpga_log(
    text: str, *, source_log: str = "<memory>"
) -> Refactor31RealSliceFPGARun:
    """Parse the one aggregate correctness/timing row from a real-slice run."""

    matches: list[tuple[int, str]] = []
    for line_number, raw_line in enumerate(text.splitlines(), start=1):
        line = raw_line.strip()
        if line.startswith(REAL_SLICE_LINE_PREFIX):
            matches.append((line_number, line))
    if len(matches) != 1:
        raise ValueError(
            f"{source_log}: expected one {REAL_SLICE_LINE_PREFIX.strip()} "
            f"record, found {len(matches)}"
        )
    line_number, line = matches[0]
    tokens = line.split(None, 2)
    if len(tokens) < 3:
        raise ValueError(f"{source_log}:{line_number}: malformed aggregate line")
    fields = dict(KEY_VALUE_RE.findall(tokens[2]))
    source_name = f"{source_log}:{line_number}"
    return Refactor31RealSliceFPGARun(
        source_log=source_log,
        status=tokens[1],
        slice=_required(fields, "slice", source_name),
        source=_integer(fields, "source", source_name),
        vertices=_integer(fields, "vertices", source_name),
        graph_edges=_integer(fields, "graph_edges", source_name),
        resident_level=_integer(fields, "resident_level", source_name),
        rounds=_integer(fields, "rounds", source_name),
        processed_edges=_integer(fields, "processed_edges", source_name),
        reader_cycles=_integer(fields, "reader_cycles", source_name),
        compute_cycles=_integer(fields, "compute_cycles", source_name),
        paired_cycles=_integer(fields, "paired_cycles", source_name),
        dijkstra_mismatches=_integer(fields, "dijkstra_mismatches", source_name),
        reference_validated=bool(
            _integer(fields, "reference_validated", source_name)
        ),
        errors=_integer(fields, "errors", source_name),
    )


def load_refactor31_real_slice_fpga_logs(
    paths: Iterable[str | Path],
) -> list[Refactor31RealSliceFPGARun]:
    records: list[Refactor31RealSliceFPGARun] = []
    for path_value in paths:
        path = Path(path_value).resolve()
        records.append(
            parse_refactor31_real_slice_fpga_log(
                path.read_text(encoding="utf-8", errors="replace"),
                source_log=str(path),
            )
        )
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


@dataclass(frozen=True)
class Refactor31ResidualModel:
    """Non-negative shell residual added to an execution-driven cycle count."""

    fixed_cycles: float
    per_round_cycles: float

    def predict(self, raw_cycles: float, rounds: int) -> float:
        if raw_cycles < 0 or rounds <= 0:
            raise ValueError("raw_cycles must be non-negative and rounds positive")
        return raw_cycles + self.fixed_cycles + self.per_round_cycles * rounds

    def to_dict(self) -> dict[str, float]:
        return {
            "fixed_cycles": self.fixed_cycles,
            "per_round_cycles": self.per_round_cycles,
        }


def summarize_refactor31_real_slice_fpga_runs(
    records: Iterable[Refactor31RealSliceFPGARun], *, required_repeats: int = 5
) -> dict[str, Any]:
    """Gate and aggregate repeated real-slice executions from one case."""

    case_records = list(records)
    if required_repeats <= 0:
        raise ValueError("required_repeats must be positive")
    if not case_records:
        raise ValueError("real-slice FPGA summary requires at least one record")
    shape_fields = (
        "slice",
        "source",
        "vertices",
        "graph_edges",
        "resident_level",
        "rounds",
        "processed_edges",
    )
    shape_consistent = all(
        getattr(record, field) == getattr(case_records[0], field)
        for record in case_records[1:]
        for field in shape_fields
    )
    admitted = [record for record in case_records if record.correctness_admitted]
    row: dict[str, Any] = {
        "case": Path(case_records[0].slice).stem,
        "samples": len(case_records),
        "correctness_admitted_samples": len(admitted),
        "required_repeats": required_repeats,
        "shape_consistent": int(shape_consistent),
        "repeat_gate": int(len(case_records) >= required_repeats),
        "correctness_gate": int(len(admitted) == len(case_records)),
    }
    for field in shape_fields:
        row[field] = getattr(case_records[0], field)
    for field in ("reader_cycles", "compute_cycles", "paired_cycles"):
        values = [float(getattr(record, field)) for record in admitted]
        row[f"median_{field}"] = round(statistics.median(values)) if values else ""
        row[f"{field.removesuffix('_cycles')}_cv_pct"] = (
            _cv_pct(values) if values else math.nan
        )
    row["calibration_admitted"] = int(
        shape_consistent
        and bool(row["repeat_gate"])
        and bool(row["correctness_gate"])
    )
    return row


def load_refactor31_resident_sim_summary(path_value: str | Path) -> dict[str, Any]:
    """Recover the event-equivalent timing spans from one resident simulation."""

    path = Path(path_value).resolve()
    payload = json.loads(path.read_text(encoding="utf-8"))
    rounds = int(payload.get("rounds", 0))
    starts = [int(value) for value in payload.get("reader_start_cycles_per_round", [])]
    reader_ends = [
        int(value) for value in payload.get("reader_end_cycles_per_round", [])
    ]
    compute_ends = [
        int(value) for value in payload.get("compute_end_cycles_per_round", [])
    ]
    if not payload.get("resident_static_sssp", False):
        raise ValueError(f"{path}: not a resident-static SSSP result")
    if rounds <= 0 or not (
        len(starts) == len(reader_ends) == len(compute_ends) == rounds
    ):
        raise ValueError(f"{path}: invalid per-round timing shape")
    if any(
        start < 0 or reader_end < start or compute_end < start
        for start, reader_end, compute_end in zip(starts, reader_ends, compute_ends)
    ):
        raise ValueError(f"{path}: invalid per-round timing interval")
    mismatch_fields = (
        "correctness_mismatches",
        "architecture_correctness_mismatches",
        "mathematical_correctness_mismatches",
    )
    correctness_admitted = all(
        int(payload.get(field, -1)) == 0 for field in mismatch_fields
    )
    ledger_admitted = all(
        bool(payload.get(field, False))
        for field in (
            "maintenance_memory_ledger_closed",
            "maintenance_stage_ledger_closed",
            "memory_locality_ledger_match",
        )
    ) and bool(payload.get("backend_arbitration", {}).get("ledger_closed", False))
    return {
        "source_summary": str(path),
        "rounds": rounds,
        "resident_level": int(payload["resident_static_level"]),
        "raw_reader_cycles": sum(
            reader_end - start for start, reader_end in zip(starts, reader_ends)
        ),
        "raw_compute_cycles": sum(
            compute_end - start for start, compute_end in zip(starts, compute_ends)
        ),
        "raw_paired_cycles": sum(
            max(reader_end, compute_end) - start
            for start, reader_end, compute_end in zip(
                starts, reader_ends, compute_ends
            )
        ),
        "processed_edges": sum(
            int(value) for value in payload.get("processed_edges_per_round", [])
        ),
        "architecture_profile_sha256": str(
            payload.get("architecture_profile_sha256", "")
        ),
        "sst_plugin_sha256": str(payload.get("sst_plugin_sha256", "")),
        "workload_sha256": str(payload.get("workload_sha256", "")),
        "correctness_admitted": int(correctness_admitted),
        "ledger_admitted": int(ledger_admitted),
    }


def fit_refactor31_residual_model(
    rows: Iterable[dict[str, Any]], *, actual_field: str, raw_field: str
) -> Refactor31ResidualModel:
    """Fit ``actual - raw = fixed + rounds * per_round`` with NNLS."""

    samples = list(rows)
    if len(samples) < 2:
        raise ValueError("residual model requires at least two calibration rows")
    x = [float(row["rounds"]) for row in samples]
    y = [float(row[actual_field]) - float(row[raw_field]) for row in samples]
    if any(rounds <= 0 for rounds in x):
        raise ValueError("residual model rounds must be positive")

    mean_x = statistics.fmean(x)
    mean_y = statistics.fmean(y)
    centered = sum((value - mean_x) ** 2 for value in x)
    if centered > 0:
        per_round = sum(
            (rounds - mean_x) * (residual - mean_y)
            for rounds, residual in zip(x, y)
        ) / centered
        fixed = mean_y - per_round * mean_x
    else:
        fixed, per_round = mean_y, 0.0

    candidates = [
        (max(0.0, fixed), max(0.0, per_round)),
        (max(0.0, mean_y), 0.0),
        (0.0, max(0.0, sum(a * b for a, b in zip(x, y)) / sum(a * a for a in x))),
        (0.0, 0.0),
    ]
    best_fixed, best_per_round = min(
        candidates,
        key=lambda pair: sum(
            (residual - pair[0] - pair[1] * rounds) ** 2
            for rounds, residual in zip(x, y)
        ),
    )
    return Refactor31ResidualModel(best_fixed, best_per_round)


def refactor31_absolute_error_percent(actual: float, predicted: float) -> float:
    if actual <= 0:
        raise ValueError("actual cycles must be positive")
    return abs(predicted - actual) / actual * 100.0


def refactor31_spearman(actual: Iterable[float], predicted: Iterable[float]) -> float:
    """Spearman rho with average ranks for ties."""

    left = list(actual)
    right = list(predicted)
    if len(left) != len(right) or len(left) < 2:
        raise ValueError("Spearman inputs require equal lengths of at least two")

    def ranks(values: list[float]) -> list[float]:
        ordered = sorted(range(len(values)), key=lambda index: values[index])
        output = [0.0] * len(values)
        start = 0
        while start < len(ordered):
            end = start + 1
            while end < len(ordered) and values[ordered[end]] == values[ordered[start]]:
                end += 1
            rank = (start + 1 + end) / 2.0
            for position in range(start, end):
                output[ordered[position]] = rank
            start = end
        return output

    left_rank = ranks(left)
    right_rank = ranks(right)
    left_mean = statistics.fmean(left_rank)
    right_mean = statistics.fmean(right_rank)
    numerator = sum(
        (a - left_mean) * (b - right_mean)
        for a, b in zip(left_rank, right_rank)
    )
    denominator = math.sqrt(
        sum((value - left_mean) ** 2 for value in left_rank)
        * sum((value - right_mean) ** 2 for value in right_rank)
    )
    return 0.0 if denominator == 0 else numerator / denominator
