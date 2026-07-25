"""Measured event-envelope calibration for the native GraSU/ReGraph pipeline.

The C++ simulator remains the execution-driven architecture model.  This
module accounts for timing visible in the routed U55C OpenCL event windows but
not represented by the current AXI/SST core, without folding those terms into
the simulated memory or pipeline cycles.

Only records explicitly marked ``calibration`` may affect coefficients.  The
frozen ``holdout`` records are prediction-only evidence.
"""

from __future__ import annotations

import hashlib
import json
import math
import re
import statistics
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterable

from .maintenance import _solve_linear


ROOT = Path(__file__).resolve().parents[2]
DEFAULT_MATRIX = ROOT / "configs/experiments/grasu_native_hw_matrix_20260725.json"
DEFAULT_SIMULATION_DIR = (
    ROOT / "docs/evidence/grasu_native_hw_matrix/simulation"
)
DEFAULT_REPEAT_MANIFEST = (
    ROOT / "configs/experiments/grasu_native_hw_repeats_20260725.json"
)
KEY_VALUE_RE = re.compile(r"([A-Za-z_][A-Za-z0-9_]*)=([^\s]+)")

COMPONENT_TARGETS = ("update", "conversion", "compute_span")
SUMMARY_TARGETS = (*COMPONENT_TARGETS, "event_gap", "event_e2e")


@dataclass(frozen=True)
class NativeTimingRecord:
    case: str
    role: str
    family: str
    kernel_clock_mhz: float
    vertices: float
    updates: float
    update_binary_probes: float
    compactor_pma_segment_reads: float
    supersteps: float
    simulation_update_cycles: float
    simulation_conversion_cycles: float
    simulation_compute_span_cycles: float
    simulation_event_e2e_cycles: float
    hardware_update_cycles: float
    hardware_conversion_cycles: float
    hardware_compute_span_cycles: float
    hardware_event_e2e_cycles: float
    hardware_samples: int = 1
    update_cv_pct: float = 0.0
    conversion_cv_pct: float = 0.0
    compute_span_cv_pct: float = 0.0
    event_e2e_cv_pct: float = 0.0
    simulation_result: str = ""
    hardware_log: str = ""

    def feature(self, name: str) -> float:
        if not hasattr(self, name):
            raise KeyError(f"unknown native timing feature: {name}")
        value = float(getattr(self, name))
        if not math.isfinite(value) or value < 0:
            raise ValueError(f"invalid native timing feature {name}={value}")
        return value

    def simulation_cycles(self, target: str) -> float:
        if target == "event_gap":
            return 0.0
        return float(getattr(self, f"simulation_{target}_cycles"))

    def hardware_cycles(self, target: str) -> float:
        if target == "event_gap":
            return self.hardware_event_gap_cycles
        return float(getattr(self, f"hardware_{target}_cycles"))

    @property
    def hardware_event_gap_cycles(self) -> float:
        return self.hardware_event_e2e_cycles - sum(
            self.hardware_cycles(target) for target in COMPONENT_TARGETS
        )


@dataclass(frozen=True)
class MeasuredEnvelope:
    target: str
    features: tuple[str, ...]
    intercept_cycles: float
    coefficients: tuple[float, ...]
    semantic: str
    samples: int
    r2: float

    def predict(self, record: NativeTimingRecord) -> float:
        value = self.intercept_cycles + sum(
            coefficient * record.feature(feature)
            for feature, coefficient in zip(self.features, self.coefficients)
        )
        return max(0.0, value)


@dataclass(frozen=True)
class NativeTimingModel:
    envelopes: dict[str, MeasuredEnvelope]
    calibration_cases: tuple[str, ...]
    kernel_clock_mhz: float
    claim_class: str = "hardware_event_window_calibrated_partial_repeats"
    limitations: tuple[str, ...] = field(
        default_factory=lambda: (
            "The fitted targets are OpenCL event windows, not on-kernel cycle counters.",
            "Four tiny cases use six repeats; the remaining small/medium cases still have one sample.",
            "The measured envelope is valid only for the pinned U55C xclbin/profile until transferred.",
        )
    )

    def component_prediction(
        self, record: NativeTimingRecord, target: str
    ) -> dict[str, float]:
        envelope = self.envelopes[target].predict(record)
        baseline = record.simulation_cycles(target)
        calibrated = baseline + envelope
        hardware = record.hardware_cycles(target)
        return _prediction_values(baseline, envelope, calibrated, hardware)

    def predict(self, record: NativeTimingRecord) -> dict[str, Any]:
        components = {
            target: self.component_prediction(record, target)
            for target in (*COMPONENT_TARGETS, "event_gap")
        }
        calibrated_e2e = sum(
            components[target]["calibrated_cycles"]
            for target in (*COMPONENT_TARGETS, "event_gap")
        )
        event_e2e = _prediction_values(
            record.simulation_event_e2e_cycles,
            calibrated_e2e - record.simulation_event_e2e_cycles,
            calibrated_e2e,
            record.hardware_event_e2e_cycles,
        )
        return {
            "case": record.case,
            "role": record.role,
            "family": record.family,
            "vertices": record.vertices,
            "updates": record.updates,
            "update_binary_probes": record.update_binary_probes,
            "compactor_pma_segment_reads": record.compactor_pma_segment_reads,
            "supersteps": record.supersteps,
            "hardware_samples": record.hardware_samples,
            "update_cv_pct": record.update_cv_pct,
            "conversion_cv_pct": record.conversion_cv_pct,
            "compute_span_cv_pct": record.compute_span_cv_pct,
            "event_e2e_cv_pct": record.event_e2e_cv_pct,
            "components": components,
            "event_e2e": event_e2e,
            "ledger_closure_cycles": calibrated_e2e
            - sum(
                components[target]["calibrated_cycles"]
                for target in (*COMPONENT_TARGETS, "event_gap")
            ),
        }


def parse_native_hardware_log(text: str) -> dict[str, Any]:
    parsed: dict[str, Any] = {}
    for line in text.splitlines():
        fields = dict(KEY_VALUE_RE.findall(line))
        if line.startswith("PURE_PIPELINE_INPUT "):
            parsed["input"] = {key: int(value) for key, value in fields.items()}
        elif line.startswith("PURE_PIPELINE_TIMING "):
            parsed["timing_ms"] = {
                key.removesuffix("_ms"): float(value)
                for key, value in fields.items()
                if key.endswith("_ms")
            }
        elif line.startswith("PURE_PIPELINE_RESULT "):
            parsed["result"] = {
                key: value if key == "status" else int(value)
                for key, value in fields.items()
            }
    missing = [key for key in ("input", "timing_ms", "result") if key not in parsed]
    if missing:
        raise ValueError(f"native hardware log is missing {', '.join(missing)}")
    if parsed["result"].get("status") != "PASS":
        raise ValueError("native hardware log does not report PASS")
    return parsed


def load_native_timing_records(
    matrix_path: Path = DEFAULT_MATRIX,
    simulation_dir: Path = DEFAULT_SIMULATION_DIR,
    repeat_manifest_path: Path | None = DEFAULT_REPEAT_MANIFEST,
    roles: Iterable[str] = ("calibration", "holdout"),
) -> list[NativeTimingRecord]:
    matrix_path = matrix_path.resolve()
    simulation_dir = simulation_dir.resolve()
    matrix = json.loads(matrix_path.read_text(encoding="utf-8"))
    repeats = _load_repeat_manifest(repeat_manifest_path, matrix_path)
    requested_roles = frozenset(roles)
    if not requested_roles or not requested_roles <= {"calibration", "holdout", "stress"}:
        raise ValueError(f"invalid native timing roles: {sorted(requested_roles)}")
    profile = json.loads((ROOT / str(matrix["profile"])).read_text(encoding="utf-8"))
    kernel_clock_mhz = float(
        next(clock for clock in profile["clocks"] if clock["name"] == "kernel")[
            "achieved_mhz"
        ]
    )

    records: list[NativeTimingRecord] = []
    for case in matrix["cases"]:
        if case["role"] not in requested_roles:
            continue
        simulation_path = simulation_dir / f"{case['case']}.result.json"
        if not simulation_path.is_file():
            if case["role"] == "stress":
                continue
            raise FileNotFoundError(simulation_path)
        simulation = json.loads(simulation_path.read_text(encoding="utf-8"))
        if simulation.get("success") is not True or simulation.get("mode") != "grasu_regraph_native_sssp":
            raise ValueError(f"{case['case']}: invalid native simulation result")
        hardware_paths = repeats.get(
            str(case["case"]), [(ROOT / str(case["hardware_log"])).resolve()]
        )
        hardware_samples = [
            parse_native_hardware_log(path.read_text(encoding="utf-8"))
            for path in hardware_paths
        ]
        _validate_repeat_structure(str(case["case"]), hardware_samples)
        timings = [sample["timing_ms"] for sample in hardware_samples]
        update_values = [float(timing["grasu"]) for timing in timings]
        conversion_values = [
            float(timing["barrier"]) + float(timing["pma_compact"])
            for timing in timings
        ]
        compute_values = [float(timing["hbm"]) for timing in timings]
        e2e_values = [float(timing["event_e2e"]) for timing in timings]
        to_cycles = kernel_clock_mhz * 1000.0
        records.append(
            NativeTimingRecord(
                case=str(case["case"]),
                role=str(case["role"]),
                family=str(case["family"]),
                kernel_clock_mhz=kernel_clock_mhz,
                vertices=float(simulation["vertices"]),
                updates=float(simulation["updates"]),
                update_binary_probes=float(simulation["update_binary_probes"]),
                compactor_pma_segment_reads=float(
                    simulation["compactor_pma_segment_reads"]
                ),
                supersteps=float(simulation["supersteps"]),
                simulation_update_cycles=float(simulation["update_cycles"]),
                simulation_conversion_cycles=float(simulation["conversion_cycles"]),
                simulation_compute_span_cycles=float(simulation["compute_cycles"]),
                simulation_event_e2e_cycles=float(simulation["cycles"]),
                hardware_update_cycles=statistics.median(update_values) * to_cycles,
                hardware_conversion_cycles=statistics.median(conversion_values)
                * to_cycles,
                hardware_compute_span_cycles=statistics.median(compute_values)
                * to_cycles,
                hardware_event_e2e_cycles=statistics.median(e2e_values) * to_cycles,
                hardware_samples=len(hardware_samples),
                update_cv_pct=_cv_pct(update_values),
                conversion_cv_pct=_cv_pct(conversion_values),
                compute_span_cv_pct=_cv_pct(compute_values),
                event_e2e_cv_pct=_cv_pct(e2e_values),
                simulation_result=str(simulation_path),
                hardware_log=";".join(str(path) for path in hardware_paths),
            )
        )
    return records


def fit_native_timing_model(
    records: Iterable[NativeTimingRecord],
) -> NativeTimingModel:
    all_records = list(records)
    calibration = [record for record in all_records if record.role == "calibration"]
    if len(calibration) < 5:
        raise ValueError("native timing fit requires at least five calibration records")
    clocks = {record.kernel_clock_mhz for record in calibration}
    if len(clocks) != 1:
        raise ValueError("native timing calibration mixes kernel clocks")

    specifications = {
        "update": (
            ("updates", "update_binary_probes"),
            "kernel/event startup plus per-update issue and binary-probe AXI/controller gap",
        ),
        "conversion": (
            ("compactor_pma_segment_reads",),
            "compactor/event startup plus per-segment AXI platform gap",
        ),
        "compute_span": (
            ("supersteps", "vertices"),
            "per-superstep ReGraph controller envelope plus first-sweep vertex-scale gap",
        ),
        "event_gap": (
            ("supersteps", "vertices"),
            "host out-of-order queue scheduling and inter-kernel event-window gaps",
        ),
    }
    envelopes = {
        target: _fit_envelope(calibration, target, features, semantic)
        for target, (features, semantic) in specifications.items()
    }
    return NativeTimingModel(
        envelopes=envelopes,
        calibration_cases=tuple(record.case for record in calibration),
        kernel_clock_mhz=clocks.pop(),
    )


def native_prediction_rows(
    model: NativeTimingModel, records: Iterable[NativeTimingRecord]
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for record in records:
        prediction = model.predict(record)
        row: dict[str, Any] = {
            key: prediction[key]
            for key in (
                "case",
                "role",
                "family",
                "vertices",
                "updates",
                "update_binary_probes",
                "compactor_pma_segment_reads",
                "supersteps",
                "hardware_samples",
                "update_cv_pct",
                "conversion_cv_pct",
                "compute_span_cv_pct",
                "event_e2e_cv_pct",
                "ledger_closure_cycles",
            )
        }
        for target in SUMMARY_TARGETS:
            values = (
                prediction["event_e2e"]
                if target == "event_e2e"
                else prediction["components"][target]
            )
            for key, value in values.items():
                row[f"{target}_{key}"] = value
        rows.append(row)
    return rows


def native_group_summary(rows: Iterable[dict[str, Any]]) -> list[dict[str, Any]]:
    materialized = list(rows)
    roles = sorted({str(row["role"]) for row in materialized})
    output: list[dict[str, Any]] = []
    for role in (*roles, "all"):
        selected = (
            materialized
            if role == "all"
            else [row for row in materialized if row["role"] == role]
        )
        for target in SUMMARY_TARGETS:
            baseline = [
                float(row[f"{target}_baseline_absolute_error_pct"])
                for row in selected
            ]
            calibrated = [
                float(row[f"{target}_calibrated_absolute_error_pct"])
                for row in selected
            ]
            output.append(
                {
                    "role": role,
                    "target": target,
                    "cases": len(selected),
                    "baseline_median_absolute_error_pct": statistics.median(baseline),
                    "baseline_max_absolute_error_pct": max(baseline),
                    "calibrated_median_absolute_error_pct": statistics.median(calibrated),
                    "calibrated_max_absolute_error_pct": max(calibrated),
                    "calibrated_median_signed_error_pct": statistics.median(
                        float(row[f"{target}_calibrated_signed_error_pct"])
                        for row in selected
                    ),
                }
            )
    return output


def native_timing_model_to_dict(model: NativeTimingModel) -> dict[str, Any]:
    return {
        "schema_version": 1,
        "claim_class": model.claim_class,
        "kernel_clock_mhz": model.kernel_clock_mhz,
        "fit_role": "calibration_only",
        "calibration_cases": list(model.calibration_cases),
        "envelopes": {
            target: {
                "target": envelope.target,
                "features": list(envelope.features),
                "intercept_cycles": envelope.intercept_cycles,
                "coefficients": dict(
                    zip(envelope.features, envelope.coefficients)
                ),
                "semantic": envelope.semantic,
                "samples": envelope.samples,
                "calibration_r2": envelope.r2,
            }
            for target, envelope in model.envelopes.items()
        },
        "limitations": list(model.limitations),
    }


def _target_residual(record: NativeTimingRecord, target: str) -> float:
    return record.hardware_cycles(target) - record.simulation_cycles(target)


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for block in iter(lambda: source.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def _load_repeat_manifest(
    path: Path | None, matrix_path: Path
) -> dict[str, list[Path]]:
    if path is None:
        return {}
    path = path.resolve()
    manifest = json.loads(path.read_text(encoding="utf-8"))
    if manifest.get("schema_version") != 1:
        raise ValueError("native repeat manifest has unsupported schema")
    if manifest.get("measurement_policy") != "componentwise_median":
        raise ValueError("native repeat manifest has unsupported measurement policy")
    if manifest.get("base_matrix_sha256") != _sha256(matrix_path):
        raise ValueError("native repeat manifest base matrix SHA-256 mismatch")
    result: dict[str, list[Path]] = {}
    for case in manifest.get("cases", []):
        name = str(case["case"])
        if name in result or not case.get("logs"):
            raise ValueError(f"invalid native repeat case: {name}")
        paths: list[Path] = []
        for entry in case["logs"]:
            log_path = (ROOT / str(entry["path"])).resolve()
            if not log_path.is_file() or _sha256(log_path) != entry["sha256"]:
                raise ValueError(f"native repeat log SHA-256 mismatch: {log_path}")
            paths.append(log_path)
        result[name] = paths
    return result


def _validate_repeat_structure(case: str, samples: list[dict[str, Any]]) -> None:
    first_input = samples[0]["input"]
    first_result = samples[0]["result"]
    for sample in samples[1:]:
        if sample["input"] != first_input or sample["result"] != first_result:
            raise ValueError(f"{case}: repeated hardware runs changed structure/result")


def _cv_pct(values: list[float]) -> float:
    mean = statistics.mean(values)
    return statistics.pstdev(values) / mean * 100.0 if mean else 0.0


def _fit_envelope(
    records: list[NativeTimingRecord],
    target: str,
    features: tuple[str, ...],
    semantic: str,
) -> MeasuredEnvelope:
    means = [statistics.mean(record.feature(feature) for record in records) for feature in features]
    scales = [
        statistics.pstdev(record.feature(feature) for record in records) or 1.0
        for feature in features
    ]
    design = [
        [
            1.0,
            *[
                (record.feature(feature) - means[index]) / scales[index]
                for index, feature in enumerate(features)
            ],
        ]
        for record in records
    ]
    targets = [_target_residual(record, target) for record in records]
    beta = _least_squares(design, targets)
    coefficients = tuple(
        beta[index + 1] / scales[index] for index in range(len(features))
    )
    intercept = beta[0] - sum(
        coefficient * mean for coefficient, mean in zip(coefficients, means)
    )
    if intercept < 0 or any(coefficient < 0 for coefficient in coefficients):
        raise ValueError(
            f"{target} measured-envelope fit produced a negative mechanism coefficient"
        )
    predictions = [
        intercept
        + sum(
            coefficient * record.feature(feature)
            for coefficient, feature in zip(coefficients, features)
        )
        for record in records
    ]
    return MeasuredEnvelope(
        target=target,
        features=features,
        intercept_cycles=intercept,
        coefficients=coefficients,
        semantic=semantic,
        samples=len(records),
        r2=_r2(targets, predictions),
    )


def _least_squares(design: list[list[float]], targets: list[float]) -> list[float]:
    if not design or len(design) != len(targets):
        raise ValueError("invalid native timing least-squares input")
    width = len(design[0])
    if len(design) < width:
        raise ValueError("native timing fit is underdetermined")
    xtx = [[0.0 for _ in range(width)] for _ in range(width)]
    xty = [0.0 for _ in range(width)]
    for row, target in zip(design, targets):
        if len(row) != width:
            raise ValueError("native timing design matrix is ragged")
        for left in range(width):
            xty[left] += row[left] * target
            for right in range(width):
                xtx[left][right] += row[left] * row[right]
    return _solve_linear(xtx, xty)


def _prediction_values(
    baseline: float, envelope: float, calibrated: float, hardware: float
) -> dict[str, float]:
    if hardware <= 0:
        raise ValueError("native timing hardware target must be positive")
    baseline_signed = (baseline - hardware) / hardware * 100.0
    calibrated_signed = (calibrated - hardware) / hardware * 100.0
    return {
        "hardware_cycles": hardware,
        "baseline_cycles": baseline,
        "measured_envelope_cycles": envelope,
        "calibrated_cycles": calibrated,
        "baseline_signed_error_pct": baseline_signed,
        "baseline_absolute_error_pct": abs(baseline_signed),
        "calibrated_signed_error_pct": calibrated_signed,
        "calibrated_absolute_error_pct": abs(calibrated_signed),
    }


def _r2(actual: list[float], predicted: list[float]) -> float:
    mean = statistics.mean(actual)
    total = sum((value - mean) ** 2 for value in actual)
    if total == 0:
        return 1.0
    residual = sum((value - estimate) ** 2 for value, estimate in zip(actual, predicted))
    return 1.0 - residual / total
