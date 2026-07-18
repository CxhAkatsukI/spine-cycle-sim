"""HW maintenance calibration utilities.

The calibration flow intentionally treats the FPGA build as a black box.  It
parses the existing host stdout, preserves raw logs, and fits lightweight
empirical models from the exported maintenance counters.
"""

from __future__ import annotations

import csv
import json
import re
import shlex
import statistics
import subprocess
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

DEFAULT_FREQ_MHZ = 134.0
CALIBRATED_L0_SCAN_ITERATION_CYCLES = 105
CALIBRATED_L0_OUTPUT_EDGE_CYCLES = 110
CALIBRATED_CARRY_SCAN_ITERATION_CYCLES = 145
CALIBRATED_CARRY_PAYLOAD_OUTPUT_EDGE_CYCLES = 80
CALIBRATED_CARRY_ROW_CURSOR_CYCLES = 130
CALIBRATED_REFILL_STALLS_PER_PAGE = 261
CALIBRATED_REFILL_STALL_CYCLES = 1
DEFAULT_HOST_EXE = (
    "/home/chuxiao/spine-dynamic-graph-reduce-levels/tests/test_integration/"
    "host_partitioned_csr_e2e_smoke"
)
DEFAULT_XRT_SETUP = "/opt/xilinx/xrt/setup.sh"
KEY_VALUE_RE = re.compile(r"([A-Za-z_][A-Za-z0-9_]*)=([^ \t\r\n]+)")

DEFAULT_FEATURES = [
    "batch_edges",
    "target_level",
    "source_count",
    "persisted_median",
    "l0_partitions_written_median",
    "l0_pages_epoch_stamped_median",
    "cold_page_ids_written_median",
    "cold_pages_visited_median",
    "cold_bits_inspected_median",
    "cold_rows_entered_median",
    "cold_payload_reads_median",
    "cold_refill_stalls_median",
    "cold_merge_inputs_median",
    "cold_outputs_median",
    "sim_structural_estimated_cycles",
    "sim_maintenance_estimated_cycles",
]

RAW_FIELD_ORDER = [
    "case",
    "sweep",
    "mode",
    "repeat",
    "returncode",
    "status",
    "path",
    "target_level",
    "batch_edges",
    "source_count",
    "timeout_s",
    "maint_ms",
    "hw_cycles",
    "stdout_log",
    "stderr_log",
    "command_log",
    "command",
]

SUMMARY_FIELD_ORDER = [
    "case",
    "sweep",
    "mode",
    "target_level",
    "batch_edges",
    "source_count",
    "expected_path",
    "repeats",
    "successful_repeats",
    "median_maint_ms",
    "min_maint_ms",
    "max_maint_ms",
    "maint_ms_jitter_pct",
    "median_hw_cycles",
    "min_hw_cycles",
    "max_hw_cycles",
]


@dataclass(frozen=True)
class ExperimentSpec:
    case: str
    sweep: str
    mode: str
    args: tuple[str, ...]
    target_level: int
    batch_edges: int
    source_count: int
    expected_path: str

    def to_row(self) -> dict[str, Any]:
        row = asdict(self)
        row["args"] = " ".join(self.args)
        return row

    @classmethod
    def from_row(cls, row: dict[str, Any]) -> "ExperimentSpec":
        args = row.get("args", ())
        if isinstance(args, str):
            args_tuple = tuple(args.split())
        else:
            args_tuple = tuple(str(value) for value in args)
        return cls(
            case=str(row["case"]),
            sweep=str(row.get("sweep", "")),
            mode=str(row.get("mode", "")),
            args=args_tuple,
            target_level=int(float(row.get("target_level", 0))),
            batch_edges=int(float(row.get("batch_edges", 0))),
            source_count=int(float(row.get("source_count", 0))),
            expected_path=str(row.get("expected_path", "")),
        )


def default_matrix() -> list[ExperimentSpec]:
    specs: list[ExperimentSpec] = []

    for edges in [256, 1024, 4096, 16_384, 65_536, 131_072]:
        specs.append(
            ExperimentSpec(
                case=f"l0_store_e{edges}",
                sweep="l0_store",
                mode="l0_store",
                args=("--star", str(edges)),
                target_level=0,
                batch_edges=edges,
                source_count=1,
                expected_path="store_l0",
            )
        )

    for edges in [256, 1024, 4096, 16_384, 65_536]:
        specs.append(
            ExperimentSpec(
                case=f"carry_l1_batch_e{edges}_s64",
                sweep="l1_batch_edges",
                mode="carry",
                args=("--measure-carry", "1", str(edges), "64"),
                target_level=1,
                batch_edges=edges,
                source_count=64,
                expected_path="cascade",
            )
        )

    for sources in [1, 16, 64, 256, 512]:
        specs.append(
            ExperimentSpec(
                case=f"carry_source_t9_e128_s{sources}",
                sweep="source_count",
                mode="carry",
                args=("--measure-carry", "9", "128", str(sources)),
                target_level=9,
                batch_edges=128,
                source_count=sources,
                expected_path="cascade",
            )
        )

    for target in [2, 3, 4]:
        specs.append(
            ExperimentSpec(
                case=f"carry_target_l{target}_e4096_s64",
                sweep="target_level",
                mode="carry",
                args=("--measure-carry", str(target), "4096", "64"),
                target_level=target,
                batch_edges=4096,
                source_count=64,
                expected_path="cascade",
            )
        )

    return specs


def _coerce_scalar(value: str) -> int | float | str:
    if value in {"PASS", "FAIL"}:
        return value
    try:
        if any(char in value for char in ".eE"):
            return float(value)
        return int(value, 0)
    except ValueError:
        return value


def _parse_key_values(line: str) -> dict[str, int | float | str]:
    values = {key: _coerce_scalar(value) for key, value in KEY_VALUE_RE.findall(line)}
    if "case" in values:
        values["host_case"] = values.pop("case")
    return values


def parse_hw_maintenance_output(stdout: str) -> dict[str, Any]:
    """Parse existing host stdout for one maintenance calibration run."""

    parsed: dict[str, Any] = {}
    for raw_line in stdout.splitlines():
        line = raw_line.strip()
        if not line:
            continue
        if line.startswith("PARTITIONED_CSR_E2E_MEASURE_CARRY_COUNTERS"):
            parsed["mode"] = "carry"
            parsed["path"] = "cascade"
            parsed.update(_parse_key_values(line))
            continue
        if line.startswith("PARTITIONED_CSR_E2E_MEASURE_CARRY "):
            parsed["mode"] = "carry"
            parsed["path"] = "cascade"
            if " PASS " in f" {line} ":
                parsed["status"] = "PASS"
            elif " FAIL " in f" {line} ":
                parsed["status"] = "FAIL"
            parsed.update(_parse_key_values(line))
            continue
        if line.startswith("PARTITIONED_CSR_E2E_BATCH "):
            parsed["mode"] = "l0_store"
            parsed.update(_parse_key_values(line))
            target = parsed.get("target_level")
            if target == 0:
                parsed["path"] = "store_l0"
            continue

    if "maint_ms" in parsed and "status" not in parsed:
        overflow = parsed.get("overflow")
        parsed["status"] = "PASS" if overflow in {0, "0", None} else "FAIL"
    return parsed


def build_hw_command(
    spec: ExperimentSpec,
    host_exe: str | Path,
    xclbin: str | Path,
    timeout_s: int,
    xrt_setup: str | Path | None = DEFAULT_XRT_SETUP,
    split_kernels: bool = True,
) -> str:
    invocation = [
        str(host_exe),
        str(xclbin),
        *spec.args,
        "--timeout",
        str(timeout_s),
    ]
    parts: list[str] = []
    if xrt_setup:
        parts.append(f"source {shlex.quote(str(xrt_setup))}")
    parts.append("unset XCL_EMULATION_MODE")
    if split_kernels:
        parts.append("export SPINE_PARTITIONED_SPLIT=1")
    parts.append(" ".join(shlex.quote(value) for value in invocation))
    return " && ".join(parts)


def run_hw_case(
    spec: ExperimentSpec,
    repeat: int,
    host_exe: str | Path,
    xclbin: str | Path,
    timeout_s: int,
    freq_mhz: float = DEFAULT_FREQ_MHZ,
    xrt_setup: str | Path | None = DEFAULT_XRT_SETUP,
    split_kernels: bool = True,
    subprocess_timeout_s: int | None = None,
) -> tuple[dict[str, Any], str, str]:
    command = build_hw_command(
        spec,
        host_exe=host_exe,
        xclbin=xclbin,
        timeout_s=timeout_s,
        xrt_setup=xrt_setup,
        split_kernels=split_kernels,
    )
    deadline = subprocess_timeout_s or (timeout_s + 90)
    completed = subprocess.run(
        ["bash", "-lc", command],
        cwd=str(Path(host_exe).resolve().parent),
        text=True,
        capture_output=True,
        timeout=deadline,
        check=False,
    )
    row = spec.to_row()
    row.update(
        {
            "repeat": repeat,
            "returncode": completed.returncode,
            "timeout_s": timeout_s,
            "command": command,
        }
    )
    parsed = parse_hw_maintenance_output(completed.stdout)
    row.update(parsed)
    if "maint_ms" in row:
        row["hw_cycles"] = float(row["maint_ms"]) * freq_mhz * 1000.0
    if "status" not in row:
        row["status"] = "PASS" if completed.returncode == 0 else "FAIL"
    return row, completed.stdout, completed.stderr


def write_json(path: Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def write_rows_csv(path: Path, rows: list[dict[str, Any]], preferred: list[str] | None = None) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fieldnames = _ordered_fields(rows, preferred or [])
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames, extrasaction="ignore")
        writer.writeheader()
        for row in rows:
            writer.writerow(row)


def read_rows_csv(path: Path) -> list[dict[str, Any]]:
    with path.open(newline="", encoding="utf-8") as handle:
        rows = list(csv.DictReader(handle))
    return [{key: _coerce_csv_value(value) for key, value in row.items()} for row in rows]


def _coerce_csv_value(value: str) -> int | float | str:
    if value == "":
        return ""
    return _coerce_scalar(value)


def _ordered_fields(rows: list[dict[str, Any]], preferred: list[str]) -> list[str]:
    present = set()
    for row in rows:
        present.update(row)
    ordered = [field for field in preferred if field in present]
    ordered.extend(sorted(present - set(ordered)))
    return ordered


def _is_number(value: Any) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def _numeric_or_none(value: Any) -> float | None:
    if _is_number(value):
        return float(value)
    if isinstance(value, str) and value:
        try:
            return float(value)
        except ValueError:
            return None
    return None


def _is_success(row: dict[str, Any]) -> bool:
    return int(float(row.get("returncode", 1))) == 0 and str(row.get("status", "")) != "FAIL"


def aggregate_rows(rows: list[dict[str, Any]], freq_mhz: float = DEFAULT_FREQ_MHZ) -> list[dict[str, Any]]:
    grouped: dict[str, list[dict[str, Any]]] = {}
    for row in rows:
        grouped.setdefault(str(row["case"]), []).append(row)

    summaries: list[dict[str, Any]] = []
    for case, case_rows in sorted(grouped.items()):
        first = case_rows[0]
        success_rows = [row for row in case_rows if _is_success(row)]
        summary: dict[str, Any] = {
            "case": case,
            "sweep": first.get("sweep", ""),
            "mode": first.get("mode", ""),
            "target_level": first.get("target_level", 0),
            "batch_edges": first.get("batch_edges", 0),
            "source_count": first.get("source_count", 0),
            "expected_path": first.get("expected_path", ""),
            "repeats": len(case_rows),
            "successful_repeats": len(success_rows),
        }

        maint_values = _values_for(success_rows, "maint_ms")
        if maint_values:
            median_ms = statistics.median(maint_values)
            min_ms = min(maint_values)
            max_ms = max(maint_values)
            summary.update(
                {
                    "median_maint_ms": median_ms,
                    "min_maint_ms": min_ms,
                    "max_maint_ms": max_ms,
                    "maint_ms_jitter_pct": (
                        ((max_ms - min_ms) / median_ms) * 100.0 if median_ms else 0.0
                    ),
                    "median_hw_cycles": median_ms * freq_mhz * 1000.0,
                    "min_hw_cycles": min_ms * freq_mhz * 1000.0,
                    "max_hw_cycles": max_ms * freq_mhz * 1000.0,
                }
            )

        numeric_keys = sorted(
            key
            for row in success_rows
            for key, value in row.items()
            if _numeric_or_none(value) is not None
            and key
            not in {
                "repeat",
                "returncode",
                "timeout_s",
                "hw_cycles",
                "maint_ms",
                "target_level",
                "batch_edges",
                "source_count",
            }
        )
        for key in numeric_keys:
            values = _values_for(success_rows, key)
            if values:
                summary[f"{key}_median"] = statistics.median(values)
        summaries.append(summary)
    return summaries


def _values_for(rows: list[dict[str, Any]], key: str) -> list[float]:
    values: list[float] = []
    for row in rows:
        value = _numeric_or_none(row.get(key))
        if value is not None:
            values.append(value)
    return values


def merge_simulator_counters(summary_rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    merged: list[dict[str, Any]] = []
    for row in summary_rows:
        updated = dict(row)
        try:
            spec = ExperimentSpec(
                case=str(row["case"]),
                sweep=str(row.get("sweep", "")),
                mode=str(row.get("mode", "")),
                args=(),
                target_level=int(float(row.get("target_level", 0))),
                batch_edges=int(float(row.get("batch_edges", 0))),
                source_count=int(float(row.get("source_count", 1) or 1)),
                expected_path=str(row.get("expected_path", "")),
            )
            updated.update(_simulate_spec_counters(spec))
        except Exception as exc:  # pragma: no cover - diagnostic path
            updated["sim_error"] = str(exc)
        merged.append(updated)
    return merged


def _simulate_spec_counters(spec: ExperimentSpec) -> dict[str, Any]:
    event = _estimate_structural_event(spec)
    return {
        "sim_structural_estimated_cycles": event["structural_estimated_cycles"],
        "sim_maintenance_estimated_cycles": event["estimated_cycles"],
        "sim_scan_passes": event["scan_passes"],
        "sim_scan_cycles": event["scan_cycles"],
        "sim_calibrated_scan_cycles": event["calibrated_scan_cycles"],
        "sim_pages_visited": event["pages_visited"],
        "sim_bits_inspected": event["bits_inspected"],
        "sim_rows_entered": event["rows_entered"],
        "sim_payload_reads": event["payload_reads"],
        "sim_refill_stalls": event["refill_stalls"],
        "sim_merge_inputs": event["merge_inputs"],
        "sim_outputs": event["outputs"],
        "sim_page_ids_written": event["page_ids_written"],
        "sim_output_edges": event["output_edges"],
        "sim_target_level": event["target_level"],
    }


def _estimate_structural_event(spec: ExperimentSpec) -> dict[str, int]:
    family_count = 16
    page_size = 256
    if spec.mode == "l0_store":
        output_edges = spec.batch_edges
        output_rows = family_count
        output_pages = family_count
        scan_passes = 1 + family_count + family_count
        scan_cycles = scan_passes * spec.batch_edges
        write_output_cycles = output_edges + output_rows + output_pages
        metadata_cycles = family_count
        structural_estimated_cycles = scan_cycles + write_output_cycles + metadata_cycles
        calibrated_scan_cycles = scan_cycles * CALIBRATED_L0_SCAN_ITERATION_CYCLES
        calibrated_write_output_cycles = (
            output_edges * CALIBRATED_L0_OUTPUT_EDGE_CYCLES + output_rows + output_pages
        )
        estimated_cycles = calibrated_scan_cycles + calibrated_write_output_cycles + metadata_cycles
        return {
            "target_level": 0,
            "output_edges": output_edges,
            "scan_passes": scan_passes,
            "scan_cycles": scan_cycles,
            "calibrated_scan_cycles": calibrated_scan_cycles,
            "pages_visited": 0,
            "bits_inspected": 0,
            "rows_entered": 0,
            "payload_reads": 0,
            "refill_stalls": 0,
            "merge_inputs": 0,
            "outputs": output_edges,
            "page_ids_written": output_pages,
            "structural_estimated_cycles": structural_estimated_cycles,
            "estimated_cycles": estimated_cycles,
        }

    target = max(1, spec.target_level)
    target_batches = 1 << target
    old_batches = target_batches - 1
    source_count = max(1, spec.source_count)
    old_edges = spec.batch_edges * old_batches
    new_edges = spec.batch_edges
    output_edges = spec.batch_edges * target_batches
    pages_visited_per_family = 0
    rows_entered_per_family = 0
    old_pages_union: set[int] = set()
    old_rows_total = 0
    for level in range(target):
        start = target_batches - (1 << (level + 1))
        batch_count = 1 << level
        sources = {(start + offset) % source_count for offset in range(batch_count)}
        pages = {source // page_size for source in sources}
        rows_entered_per_family += len(sources)
        pages_visited_per_family += len(pages)
        old_pages_union.update(pages)
        old_rows_total += len(sources) * family_count
    new_source = (target_batches - 1) % source_count
    output_pages_per_family = len(old_pages_union | {new_source // page_size})
    new_rows = family_count

    pages_visited = pages_visited_per_family * family_count
    bits_inspected = pages_visited * page_size
    rows_entered = rows_entered_per_family * family_count
    refill_stalls = pages_visited * CALIBRATED_REFILL_STALLS_PER_PAGE
    cursor_read_cycles = pages_visited * 7 + rows_entered * 2 + old_edges
    merge_inputs = old_edges + new_edges
    output_rows = old_rows_total + new_rows
    output_pages = output_pages_per_family * family_count
    scan_passes = 1 + family_count
    scan_cycles = scan_passes * spec.batch_edges
    write_output_cycles = output_edges + output_rows + output_pages
    metadata_cycles = family_count * target * 8 + family_count * 21
    structural_estimated_cycles = (
        scan_cycles
        + cursor_read_cycles
        + bits_inspected
        + merge_inputs
        + write_output_cycles
        + metadata_cycles
    )
    calibrated_scan_cycles = scan_cycles * CALIBRATED_CARRY_SCAN_ITERATION_CYCLES
    calibrated_merge_cycles = (
        (old_edges + output_edges) * CALIBRATED_CARRY_PAYLOAD_OUTPUT_EDGE_CYCLES
    )
    calibrated_row_cursor_cycles = rows_entered * CALIBRATED_CARRY_ROW_CURSOR_CYCLES
    calibrated_refill_stall_cycles = refill_stalls * CALIBRATED_REFILL_STALL_CYCLES
    estimated_cycles = (
        calibrated_scan_cycles
        + calibrated_merge_cycles
        + calibrated_row_cursor_cycles
        + calibrated_refill_stall_cycles
        + output_pages
        + metadata_cycles
    )
    return {
        "target_level": target,
        "output_edges": output_edges,
        "scan_passes": scan_passes,
        "scan_cycles": scan_cycles,
        "calibrated_scan_cycles": calibrated_scan_cycles,
        "pages_visited": pages_visited,
        "bits_inspected": bits_inspected,
        "rows_entered": rows_entered,
        "payload_reads": old_edges,
        "refill_stalls": refill_stalls,
        "merge_inputs": merge_inputs,
        "outputs": output_edges,
        "page_ids_written": output_pages,
        "structural_estimated_cycles": structural_estimated_cycles,
        "estimated_cycles": estimated_cycles,
    }


def analyze_summary(summary_rows: list[dict[str, Any]]) -> dict[str, Any]:
    rows = [row for row in summary_rows if _numeric_or_none(row.get("median_hw_cycles")) is not None]
    carry_rows = [row for row in rows if row.get("mode") == "carry"]
    return {
        "row_count": len(rows),
        "carry_row_count": len(carry_rows),
        "univariate": _univariate_scores(rows, DEFAULT_FEATURES),
        "univariate_carry": _univariate_scores(carry_rows, DEFAULT_FEATURES),
        "ridge": _ridge_fit(rows, DEFAULT_FEATURES),
        "ridge_carry": _ridge_fit(carry_rows, DEFAULT_FEATURES),
    }


def _univariate_scores(rows: list[dict[str, Any]], features: list[str]) -> list[dict[str, Any]]:
    scores: list[dict[str, Any]] = []
    y_values = [_numeric_or_none(row.get("median_hw_cycles")) for row in rows]
    clean_y = [value for value in y_values if value is not None]
    if len(clean_y) < 2:
        return scores
    for feature in features:
        pairs = [
            (x, y)
            for row in rows
            if (x := _numeric_or_none(row.get(feature))) is not None
            and (y := _numeric_or_none(row.get("median_hw_cycles"))) is not None
        ]
        if len(pairs) < 2:
            continue
        xs = [pair[0] for pair in pairs]
        ys = [pair[1] for pair in pairs]
        if max(xs) == min(xs):
            continue
        x_mean = statistics.mean(xs)
        y_mean = statistics.mean(ys)
        denom = sum((x - x_mean) ** 2 for x in xs)
        if denom == 0:
            continue
        slope = sum((x - x_mean) * (y - y_mean) for x, y in pairs) / denom
        intercept = y_mean - slope * x_mean
        predictions = [intercept + slope * x for x in xs]
        r2 = _r2_score(ys, predictions)
        scores.append(
            {
                "feature": feature,
                "slope": slope,
                "intercept": intercept,
                "r2": r2,
                "dynamic_range_cycles": abs(slope) * (max(xs) - min(xs)),
                "samples": len(pairs),
            }
        )
    scores.sort(key=lambda item: (float(item["r2"]), float(item["dynamic_range_cycles"])), reverse=True)
    return scores


def _ridge_fit(rows: list[dict[str, Any]], features: list[str], alpha: float = 1.0e-6) -> dict[str, Any]:
    records: list[tuple[list[float], float]] = []
    active_features = [
        feature
        for feature in features
        if any(_numeric_or_none(row.get(feature)) not in {None, 0.0} for row in rows)
    ]
    for row in rows:
        y = _numeric_or_none(row.get("median_hw_cycles"))
        if y is None:
            continue
        xs = [_numeric_or_none(row.get(feature)) or 0.0 for feature in active_features]
        records.append((xs, y))
    if len(records) < 2 or not active_features:
        return {"samples": len(records), "features": active_features, "r2": None}

    columns = list(zip(*(record[0] for record in records)))
    means = [statistics.mean(column) for column in columns]
    stds = [statistics.pstdev(column) or 1.0 for column in columns]
    x_rows = [
        [1.0, *[(value - means[index]) / stds[index] for index, value in enumerate(xs)]]
        for xs, _ in records
    ]
    ys = [y for _, y in records]
    dim = len(active_features) + 1
    xtx = [[0.0 for _ in range(dim)] for _ in range(dim)]
    xty = [0.0 for _ in range(dim)]
    for x_row, y in zip(x_rows, ys):
        for i in range(dim):
            xty[i] += x_row[i] * y
            for j in range(dim):
                xtx[i][j] += x_row[i] * x_row[j]
    for i in range(1, dim):
        xtx[i][i] += alpha
    beta = _solve_linear(xtx, xty)
    predictions = [sum(coef * value for coef, value in zip(beta, x_row)) for x_row in x_rows]
    residuals = [y - pred for y, pred in zip(ys, predictions)]
    median_abs_pct = statistics.median(
        [abs(error) / y * 100.0 for error, y in zip(residuals, ys) if y]
    )
    return {
        "samples": len(records),
        "features": active_features,
        "r2": _r2_score(ys, predictions),
        "median_abs_pct_error": median_abs_pct,
        "intercept": beta[0],
        "standardized_coefficients": {
            feature: beta[index + 1] for index, feature in enumerate(active_features)
        },
    }


def _solve_linear(matrix: list[list[float]], vector: list[float]) -> list[float]:
    n = len(vector)
    aug = [row[:] + [vector[index]] for index, row in enumerate(matrix)]
    for col in range(n):
        pivot = max(range(col, n), key=lambda row: abs(aug[row][col]))
        if abs(aug[pivot][col]) < 1.0e-12:
            aug[pivot][col] = 1.0e-12
        aug[col], aug[pivot] = aug[pivot], aug[col]
        denom = aug[col][col]
        for item in range(col, n + 1):
            aug[col][item] /= denom
        for row in range(n):
            if row == col:
                continue
            factor = aug[row][col]
            for item in range(col, n + 1):
                aug[row][item] -= factor * aug[col][item]
    return [aug[row][n] for row in range(n)]


def _r2_score(actual: list[float], predicted: list[float]) -> float:
    if len(actual) != len(predicted) or not actual:
        return 0.0
    mean = statistics.mean(actual)
    total = sum((value - mean) ** 2 for value in actual)
    if total == 0:
        return 1.0
    residual = sum((value - pred) ** 2 for value, pred in zip(actual, predicted))
    return 1.0 - residual / total
