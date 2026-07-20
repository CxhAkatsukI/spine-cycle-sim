"""Phase 5A reader / readmaintenance structured component model.

Scope
-----
The E2E phase found that real one-partition Amazon exact slices are
**reader-dominant**: ``median_reader_ms`` is essentially ``median_conv_span_ms``
(e.g. ``top4096`` has reader ≈ 437.86 ms, conv_span ≈ 438.30 ms). This module
decomposes that reader time into a **structured, non-negative** component model
so the bottleneck is explained by physically meaningful terms rather than by the
free-OLS coefficients (which could go negative) used in the E2E v1 reader model.

Model
-----
All coefficients are constrained ``>= 0`` (non-negative least squares)::

    R_cycles = fixed
             + c_edge_stream        * traversed_edges
             + c_replay             * active_records_x_touched_tiles
             + c_fast               * fast_gather_scatter_words
             + c_full               * full_swept_words
             + c_fallback           * fallback_penalty
             + c_partition          * partition_spread

Component meaning:

* ``fixed``               -- reader event/window fixed cost.
* ``edge_stream``         -- streaming traversed edges from HBM.
* ``active_record_replay`` -- active source records replayed across touched tiles
  (``active_records * touched_tiles``).
* ``fast_gather_scatter`` -- fast-path gather/scatter vertex words.
* ``full_sweep``          -- full-tile swept vertex words.
* ``fallback``            -- fallback / replay-fallback penalty.
* ``partition_spread``    -- multi-partition / HBM-bank spread.

Measurement-window limitation
-----------------------------
``reader_ms`` is the readmaintenance / CONV compute-unit **event duration** in
the full smoke run, not a pure hardware reader-only cycle count. Small synthetic
cases are therefore dominated by fixed overhead and timer noise, and carry high
relative error. The model is fit with relative weighting so the (much larger)
reader-dominant cases -- where the reader signal is real -- drive the
coefficients.

R stays a diagnostic sub-model of the D span (``D_tail = max(0, D_span - R)``)
and is **not** added into the serial E2E total, which remains
``B_pred + D_span_pred + overhead_model``.
"""

from __future__ import annotations

import csv
import statistics
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from .bstage import (
    BORDERLINE_MAX_ABS_PCT,
    HIGH_JITTER_PCT,
    TINY_EDGE_THRESHOLD,
    TRUSTED_MAX_ABS_PCT,
    classify_trust,
)
from .maintenance import DEFAULT_FREQ_MHZ

# ---------------------------------------------------------------------------
# Components / what-ifs
# ---------------------------------------------------------------------------

READER_COMPONENT_ORDER = [
    "fixed",
    "edge_stream",
    "active_record_replay",
    "fast_gather_scatter",
    "full_sweep",
    "fallback",
    "partition_spread",
]

#: Components that scale with a feature (i.e. everything except the constant).
_SCALING_COMPONENTS = [c for c in READER_COMPONENT_ORDER if c != "fixed"]

READER_WHATIF_ORDER = [
    "halve_active_record_replay",
    "halve_full_sweep",
    "halve_fast_gather_scatter",
    "halve_edge_stream",
    "remove_fallback_penalty",
]


def reader_feature_values(row: dict[str, Any]) -> dict[str, float]:
    """Structured, non-negative feature values for one merged evidence row."""

    traversed = _num(row.get("traversed_edges"))
    if traversed is None:
        traversed = _num(row.get("median_traversed_edges")) or 0.0
    return {
        "fixed": 1.0,
        "edge_stream": traversed,
        "active_record_replay": _num(row.get("active_records_x_touched_tiles")) or 0.0,
        "fast_gather_scatter": (
            (_num(row.get("tile_fast_gathered_words")) or 0.0)
            + (_num(row.get("tile_scattered_words")) or 0.0)
        ),
        "full_sweep": _num(row.get("tile_full_swept_words")) or 0.0,
        "fallback": (
            (_num(row.get("tile_fallback_count")) or 0.0)
            * (_num(row.get("tile_clipped_ranges")) or 0.0)
        ),
        "partition_spread": _num(row.get("tile_partition_count")) or 0.0,
    }


def path_class(row: dict[str, Any]) -> str:
    fast = _num(row.get("tile_fast_count")) or 0.0
    full = _num(row.get("tile_full_count")) or 0.0
    fallback = _num(row.get("tile_fallback_count")) or 0.0
    if fallback > 0.0:
        return "fallback"
    if fast > 0.0 and full > 0.0:
        return "mixed"
    if full > 0.0:
        return "full_only"
    if fast > 0.0:
        return "fast_only"
    return "none"


# ---------------------------------------------------------------------------
# Model
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class ReaderComponentModel:
    coefficients: dict[str, float]
    freq_mhz: float = DEFAULT_FREQ_MHZ
    weight_mode: str = "relative"
    calibration: dict[str, Any] = field(default_factory=dict)

    def components(self, row: dict[str, Any]) -> dict[str, float]:
        values = reader_feature_values(row)
        return {c: self.coefficients.get(c, 0.0) * values[c] for c in READER_COMPONENT_ORDER}

    def predicted_cycles(self, row: dict[str, Any]) -> float:
        return sum(self.components(row).values())

    def whatifs(self, row: dict[str, Any]) -> dict[str, dict[str, float]]:
        components = self.components(row)
        total = sum(components.values())
        out: dict[str, dict[str, float]] = {}
        halves = {
            "halve_active_record_replay": "active_record_replay",
            "halve_full_sweep": "full_sweep",
            "halve_fast_gather_scatter": "fast_gather_scatter",
            "halve_edge_stream": "edge_stream",
        }
        for name, component in halves.items():
            out[name] = _whatif(total, 0.5 * components[component])
        out["remove_fallback_penalty"] = _whatif(total, components["fallback"])
        return out

    def predict(
        self,
        row: dict[str, Any],
        group: str,
        role: str,
        freq_mhz: float | None = None,
    ) -> dict[str, Any] | None:
        freq = freq_mhz or self.freq_mhz
        actual = _ms_cycles(row.get("median_reader_ms"), freq)
        if actual is None or actual <= 0.0:
            return None
        components = self.components(row)
        predicted = sum(components.values())
        error_pct = (predicted - actual) / actual * 100.0
        top_component = max(components, key=lambda name: components[name])

        conv_span = _ms_cycles(row.get("median_conv_span_ms"), freq)
        kernel_e2e = _ms_cycles(row.get("median_kernel_e2e_ms"), freq)
        d_tail = max(0.0, conv_span - actual) if conv_span is not None else ""
        reader_share = (actual / conv_span) if conv_span else ""

        result: dict[str, Any] = {
            "group": group,
            "role": role,
            "case": str(row.get("case", "")),
            "sweep": str(row.get("sweep", "")),
            "path_class": path_class(row),
            "traversed_edges": reader_feature_values(row)["edge_stream"],
            "active_records": _num(row.get("median_active_records")) or "",
            "touched_tiles": _num(row.get("median_touched_tiles")) or "",
            "partition_count": _num(row.get("tile_partition_count")) or "",
            "fallback_count": _num(row.get("tile_fallback_count")) or 0.0,
            "reader_actual_cycles": actual,
            "reader_pred_cycles": predicted,
            "error_pct": error_pct,
            "abs_error_pct": abs(error_pct),
            "trusted_status": classify_trust(abs(error_pct)),
            "evidence_note": evidence_note(row, role),
            "top_component": top_component,
            "top_component_cycles": components[top_component],
            "conv_span_actual_cycles": conv_span if conv_span is not None else "",
            "kernel_e2e_actual_cycles": kernel_e2e if kernel_e2e is not None else "",
            "reader_share_of_conv_span": reader_share,
            "d_tail_cycles": d_tail,
            "components": components,
            "whatifs": self.whatifs(row),
        }
        return result


def fit_reader_component_model(
    rows: list[dict[str, Any]],
    freq_mhz: float = DEFAULT_FREQ_MHZ,
    weight_mode: str = "relative",
    iterations: int = 8000,
) -> ReaderComponentModel:
    """Non-negative least squares fit of ``median_reader_ms`` -> cycles.

    Coordinate descent with a non-negativity clamp per coefficient.  Relative
    weighting (``1/target^2``) is the default so reader-dominant cases -- where
    the reader signal dominates the CONV event window -- drive the fit instead of
    the fixed-overhead-dominated tiny cases.
    """

    records: list[tuple[list[float], float]] = []
    for row in rows:
        target = _ms_cycles(row.get("median_reader_ms"), freq_mhz)
        if target is None or target <= 0.0:
            continue
        values = reader_feature_values(row)
        records.append(([values[c] for c in READER_COMPONENT_ORDER], target))
    if len(records) < 2:
        raise ValueError("not enough reader calibration rows with median_reader_ms")

    dim = len(READER_COMPONENT_ORDER)
    columns = [[records[i][0][j] for i in range(len(records))] for j in range(dim)]
    weights = [_weight(records[i][1], weight_mode) for i in range(len(records))]
    col_norms = [
        sum(weights[i] * columns[j][i] * columns[j][i] for i in range(len(records)))
        for j in range(dim)
    ]
    coefficients = [0.0] * dim
    predictions = [0.0] * len(records)
    for _ in range(iterations):
        for j in range(dim):
            if col_norms[j] <= 0.0:
                continue
            old = coefficients[j]
            numerator = 0.0
            for i in range(len(records)):
                residual = records[i][1] - predictions[i] + old * columns[j][i]
                numerator += weights[i] * columns[j][i] * residual
            new = max(0.0, numerator / col_norms[j])
            if new == old:
                continue
            delta = new - old
            coefficients[j] = new
            for i in range(len(records)):
                predictions[i] += delta * columns[j][i]

    model = ReaderComponentModel(
        coefficients=dict(zip(READER_COMPONENT_ORDER, coefficients)),
        freq_mhz=freq_mhz,
        weight_mode=weight_mode,
    )
    model.calibration.update(_calibration_metrics(model, rows, freq_mhz))
    return model


def _calibration_metrics(
    model: ReaderComponentModel, rows: list[dict[str, Any]], freq_mhz: float
) -> dict[str, Any]:
    errors: list[float] = []
    for row in rows:
        prediction = model.predict(row, group="calibration", role="calibration", freq_mhz=freq_mhz)
        if prediction is not None:
            errors.append(prediction["abs_error_pct"])
    metrics: dict[str, Any] = {"samples": len(errors)}
    if errors:
        metrics["median_abs_pct_error"] = statistics.median(errors)
        metrics["max_abs_pct_error"] = max(errors)
    return metrics


# ---------------------------------------------------------------------------
# Evidence loading (self-contained: summary.csv + tile_schedule.csv)
# ---------------------------------------------------------------------------

_TILE_AGG_KEYS = [
    "tile_fast_count",
    "tile_full_count",
    "tile_fallback_count",
    "tile_fast_gathered_words",
    "tile_full_swept_words",
    "tile_scattered_words",
    "tile_clipped_ranges",
    "tile_partition_count",
]


def load_reader_rows(directory: str | Path) -> list[dict[str, Any]]:
    """Load a D-stage evidence directory into merged reader-feature rows.

    Reads ``summary.csv`` for the per-case medians and ``tile_schedule.csv`` for
    the per-case tile aggregates (median over repeats), then derives the
    reader-model features (including ``active_records_x_touched_tiles``).
    Self-contained so the calibration package does not depend on the scripts
    layer.
    """

    directory = Path(directory)
    summary_rows = _read_csv(directory / "summary.csv")
    tile_features = _tile_features_by_case(directory / "tile_schedule.csv")
    merged: list[dict[str, Any]] = []
    for row in summary_rows:
        if not _is_successful(row):
            continue
        case = str(row.get("case", ""))
        out = dict(row)
        out.update({key: 0.0 for key in _TILE_AGG_KEYS})
        out.update(tile_features.get(case, {}))
        touched = (out.get("tile_fast_count") or 0.0) + (out.get("tile_full_count") or 0.0)
        active_records = _num(out.get("median_active_records")) or 0.0
        out["active_records_x_touched_tiles"] = active_records * touched
        out["source_dir"] = str(directory)
        merged.append(out)
    return merged


def _tile_features_by_case(path: Path) -> dict[str, dict[str, float]]:
    if not path.exists():
        return {}
    rows = _read_csv(path)
    by_repeat: dict[tuple[str, int], dict[str, float]] = {}
    partitions: dict[tuple[str, int], set[int]] = {}
    for row in rows:
        case = str(row.get("case", ""))
        repeat = int(_num(row.get("repeat")) or 0)
        key = (case, repeat)
        agg = by_repeat.setdefault(key, {key: 0.0 for key in _TILE_AGG_KEYS})
        partitions.setdefault(key, set()).add(int(_num(row.get("partition")) or 0))
        is_fast = str(row.get("path", "")) == "fast"
        if _num(row.get("fallback_used")) or 0.0:
            agg["tile_fallback_count"] += 1.0
        agg["tile_clipped_ranges"] += _num(row.get("clipped_ranges")) or 0.0
        if is_fast:
            agg["tile_fast_count"] += 1.0
            agg["tile_fast_gathered_words"] += _num(row.get("gathered_vertex_words")) or 0.0
            agg["tile_scattered_words"] += _num(row.get("scattered_vertex_words")) or 0.0
        else:
            agg["tile_full_count"] += 1.0
            agg["tile_full_swept_words"] += _num(row.get("swept_vertex_words")) or 0.0
    for key, agg in by_repeat.items():
        agg["tile_partition_count"] = float(len(partitions.get(key, set())))

    by_case: dict[str, dict[str, float]] = {}
    cases = {case for case, _ in by_repeat}
    for case in cases:
        case_aggs = [agg for (agg_case, _), agg in by_repeat.items() if agg_case == case]
        by_case[case] = {
            key: statistics.median(agg[key] for agg in case_aggs) for key in _TILE_AGG_KEYS
        }
    return by_case


# ---------------------------------------------------------------------------
# Classification / CSV shaping
# ---------------------------------------------------------------------------


def evidence_note(row: dict[str, Any], role: str) -> str:
    notes: list[str] = []
    edges = reader_feature_values(row)["edge_stream"]
    if edges and edges < TINY_EDGE_THRESHOLD:
        notes.append(f"tiny_case_edges_lt_{TINY_EDGE_THRESHOLD}")
    jitter = _num(row.get("conv_ms_jitter_pct"))
    if jitter is not None and jitter > HIGH_JITTER_PCT:
        notes.append(f"high_jitter_gt_{HIGH_JITTER_PCT:g}pct")
    # reader_ms is a CONV event window, not pure reader cycles.
    notes.append("measurement_window")
    if role.endswith("holdout") or role == "holdout":
        notes.append("holdout")
    return ";".join(notes)


def reader_prediction_row(prediction: dict[str, Any]) -> dict[str, Any]:
    total = float(prediction["reader_pred_cycles"]) or 1.0
    row: dict[str, Any] = {
        key: prediction[key]
        for key in (
            "group",
            "role",
            "case",
            "sweep",
            "path_class",
            "traversed_edges",
            "active_records",
            "touched_tiles",
            "partition_count",
            "fallback_count",
            "reader_actual_cycles",
            "reader_pred_cycles",
            "error_pct",
            "abs_error_pct",
            "trusted_status",
            "evidence_note",
            "top_component",
            "top_component_cycles",
            "conv_span_actual_cycles",
            "kernel_e2e_actual_cycles",
            "reader_share_of_conv_span",
            "d_tail_cycles",
        )
    }
    components = prediction["components"]
    for name in READER_COMPONENT_ORDER:
        cycles = float(components.get(name, 0.0))
        row[f"comp_{name}_cycles"] = cycles
        row[f"comp_{name}_share"] = cycles / total
    for name in READER_WHATIF_ORDER:
        entry = prediction["whatifs"].get(name, {"cycles": total, "speedup": 1.0})
        row[f"whatif_{name}_cycles"] = entry["cycles"]
        row[f"whatif_{name}_speedup"] = entry["speedup"]
    return row


def reader_prediction_field_order() -> list[str]:
    order = [
        "group",
        "role",
        "case",
        "sweep",
        "path_class",
        "traversed_edges",
        "active_records",
        "touched_tiles",
        "partition_count",
        "fallback_count",
        "reader_actual_cycles",
        "reader_pred_cycles",
        "error_pct",
        "abs_error_pct",
        "trusted_status",
        "evidence_note",
        "top_component",
        "top_component_cycles",
        "conv_span_actual_cycles",
        "kernel_e2e_actual_cycles",
        "reader_share_of_conv_span",
        "d_tail_cycles",
    ]
    for name in READER_COMPONENT_ORDER:
        order.append(f"comp_{name}_cycles")
        order.append(f"comp_{name}_share")
    for name in READER_WHATIF_ORDER:
        order.append(f"whatif_{name}_cycles")
        order.append(f"whatif_{name}_speedup")
    return order


def reader_group_summary(predictions: list[dict[str, Any]]) -> list[dict[str, Any]]:
    grouped: dict[tuple[str, str], list[dict[str, Any]]] = {}
    for prediction in predictions:
        grouped.setdefault((prediction["role"], prediction["group"]), []).append(prediction)
    summaries: list[dict[str, Any]] = []
    for (role, group), preds in sorted(grouped.items()):
        abs_errors = [float(p["abs_error_pct"]) for p in preds]
        statuses = [p["trusted_status"] for p in preds]
        path_counts: dict[str, int] = {}
        for p in preds:
            path_counts[p["path_class"]] = path_counts.get(p["path_class"], 0) + 1
        top_path = max(path_counts, key=lambda name: path_counts[name])
        summaries.append(
            {
                "role": role,
                "group": group,
                "cases": len(preds),
                "median_abs_error_pct": statistics.median(abs_errors),
                "max_abs_error_pct": max(abs_errors),
                "trusted": statuses.count("trusted"),
                "borderline": statuses.count("borderline"),
                "untrusted": statuses.count("untrusted"),
                "dominant_path_class": top_path,
            }
        )
    return summaries


def reader_group_summary_field_order() -> list[str]:
    return [
        "role",
        "group",
        "cases",
        "median_abs_error_pct",
        "max_abs_error_pct",
        "trusted",
        "borderline",
        "untrusted",
        "dominant_path_class",
    ]


def reader_component_model_to_dict(model: ReaderComponentModel) -> dict[str, Any]:
    return {
        "target": "median_reader_ms",
        "target_units": "cycles",
        "backend": "nonnegative_component_v1",
        "freq_mhz": model.freq_mhz,
        "weight_mode": model.weight_mode,
        "form": (
            "R = fixed + c_edge_stream*traversed_edges "
            "+ c_replay*active_records_x_touched_tiles "
            "+ c_fast*fast_gather_scatter_words + c_full*full_swept_words "
            "+ c_fallback*fallback_penalty + c_partition*partition_spread"
        ),
        "component_order": READER_COMPONENT_ORDER,
        "whatif_order": READER_WHATIF_ORDER,
        "coefficients": model.coefficients,
        "trust_thresholds": {
            "trusted_max_abs_pct": TRUSTED_MAX_ABS_PCT,
            "borderline_max_abs_pct": BORDERLINE_MAX_ABS_PCT,
        },
        "measurement_window_note": (
            "median_reader_ms is the readmaintenance/CONV CU event duration in the "
            "full smoke run, not pure hardware reader-only cycles; tiny synthetic "
            "cases are fixed-overhead/timer-noise dominated"
        ),
        "not_separately_identifiable": [
            name
            for name in ("fallback", "partition_spread")
            if model.coefficients.get(name, 0.0) == 0.0
        ],
        "calibration": model.calibration,
    }


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _whatif(total: float, savings: float) -> dict[str, float]:
    new_total = total - savings
    speedup = (total / new_total) if new_total > 0.0 else 1.0
    return {"cycles": new_total, "speedup": speedup}


def _weight(target: float, weight_mode: str) -> float:
    if target <= 0.0:
        return 1.0
    if weight_mode == "none":
        return 1.0
    if weight_mode == "sqrt_relative":
        return 1.0 / target
    if weight_mode == "relative":
        return 1.0 / (target * target)
    raise ValueError(f"unknown weight mode: {weight_mode}")


def _is_successful(row: dict[str, Any]) -> bool:
    success = _num(row.get("successful_repeats"))
    repeats = _num(row.get("repeats"))
    if success is not None and repeats is not None and success < repeats:
        return False
    return _num(row.get("median_reader_ms")) is not None


def _read_csv(path: Path) -> list[dict[str, Any]]:
    with path.open(newline="", encoding="utf-8") as handle:
        return [dict(row) for row in csv.DictReader(handle)]


def _num(value: Any) -> float | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return float(value)
    if isinstance(value, str) and value.strip():
        try:
            return float(value)
        except ValueError:
            return None
    return None


def _ms_cycles(value: Any, freq_mhz: float) -> float | None:
    ms = _num(value)
    return None if ms is None else ms * freq_mhz * 1000.0
