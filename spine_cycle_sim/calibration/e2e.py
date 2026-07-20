"""HLS-structure-aware, evidence-calibrated end-to-end (E2E) timing model.

This is an *analysis / model layer* that composes the already-calibrated
component models into a single ledger for kernel end-to-end time.  It does not
change ``SpineV0Simulator.run()`` and it does not do full AXI/HBM/stream
cycle-accurate replay -- it reuses the existing simulator feature extraction and
component predictions.

Execution model (current measured hardware)
-------------------------------------------
The current measured execution is modeled as **serial**: maintenance (the
B-stage) completes, then the reader + convergence span (D) consumes the updated
state.  This is what the evidence shows -- across every real and synthetic
full-E2E slice, ``kernel_e2e_ms ~= maint_ms + conv_span_ms`` with a near-zero
residual.  We do **not** claim the hardware physically cannot overlap; only that
the current measured execution is modeled as serial unless dedicated overlap
evidence proves otherwise.

Ledger (avoiding double counting)
---------------------------------
``median_conv_span_ms`` already includes the reader span, so the main total is::

    serial_pred = B_pred + D_span_pred + overhead_model     (NOT B + R + D_span)

The reader ``R`` is an internal diagnostic sub-model of the D span::

    R          aligns to median_reader_ms
    D_tail     = max(0, D_span - R)     # compute/tail not covered by the reader

Overhead is a residual/fixed calibration term::

    overhead_actual = kernel_e2e_actual - B_actual - D_span_actual

If ``overhead_actual`` is negative for a case it is flagged
``overlap_or_measurement_window`` rather than interpreted as negative overhead.

The B and D span predictions are injected by the caller (the CLI wires the
Phase 4C B model and the D-stage component model); this module owns the reader
model, the overhead model, the ledger, the what-ifs, and the summaries.
"""

from __future__ import annotations

import statistics
from dataclasses import dataclass, field
from typing import Any, Callable

from .bstage import (
    BORDERLINE_MAX_ABS_PCT,
    HIGH_JITTER_PCT,
    TINY_EDGE_THRESHOLD,
    TRUSTED_MAX_ABS_PCT,
    classify_trust,
)
from .maintenance import DEFAULT_FREQ_MHZ, _solve_linear

# ---------------------------------------------------------------------------
# Reader (R) model
# ---------------------------------------------------------------------------

#: Default reader features.  The reader streams traversed edges from HBM and
#: sweeps/gathers/scatters vertex words, so reader time scales with edge and word
#: volume rather than with the maintenance partition structure.
DEFAULT_READER_FEATURES = [
    "median_traversed_edges",
    "tile_full_swept_words",
    "tile_scattered_words",
    "tile_fast_gathered_words",
    "median_active_records",
]


@dataclass(frozen=True)
class ReaderModel:
    intercept: float
    features: list[str]
    means: dict[str, float]
    stds: dict[str, float]
    coefficients: dict[str, float]

    def predict(self, row: dict[str, Any]) -> float:
        pred = self.intercept
        for feature in self.features:
            value = _num(row.get(feature)) or 0.0
            mean = self.means[feature]
            std = self.stds[feature] or 1.0
            pred += self.coefficients[feature] * ((value - mean) / std)
        return max(0.0, pred)


def fit_reader_model(
    rows: list[dict[str, Any]],
    features: list[str] | None = None,
    freq_mhz: float = DEFAULT_FREQ_MHZ,
    alpha: float = 1.0e-6,
) -> ReaderModel:
    """Unweighted standardized ridge fitting ``median_reader_ms`` -> cycles.

    Unweighted (ordinary) least squares is used deliberately: reader time spans
    several orders of magnitude across slices, and ``1/target`` weighting
    collapses the fit onto the tiniest, noisiest cases.
    """

    features = features or DEFAULT_READER_FEATURES
    active = [
        feature
        for feature in features
        if any((_num(row.get(feature)) or 0.0) != 0.0 for row in rows)
    ]
    records: list[tuple[list[float], float]] = []
    for row in rows:
        target = _reader_cycles(row, freq_mhz)
        if target is None:
            continue
        records.append(([_num(row.get(f)) or 0.0 for f in active], target))
    if len(records) < 2 or not active:
        raise ValueError("not enough reader calibration rows with median_reader_ms")

    columns = list(zip(*(xs for xs, _ in records)))
    means = [statistics.mean(col) for col in columns]
    stds = [statistics.pstdev(col) or 1.0 for col in columns]
    dim = len(active) + 1
    x_rows = [
        [1.0, *[(xs[i] - means[i]) / stds[i] for i in range(len(active))]]
        for xs, _ in records
    ]
    ys = [y for _, y in records]
    xtx = [[0.0] * dim for _ in range(dim)]
    xty = [0.0] * dim
    for x_row, y in zip(x_rows, ys):
        for i in range(dim):
            xty[i] += x_row[i] * y
            for j in range(dim):
                xtx[i][j] += x_row[i] * x_row[j]
    for i in range(1, dim):
        xtx[i][i] += alpha
    beta = _solve_linear(xtx, xty)
    return ReaderModel(
        intercept=beta[0],
        features=active,
        means=dict(zip(active, means)),
        stds=dict(zip(active, stds)),
        coefficients={feature: beta[index + 1] for index, feature in enumerate(active)},
    )


# ---------------------------------------------------------------------------
# Overhead model
# ---------------------------------------------------------------------------


def compute_overhead_model(rows: list[dict[str, Any]], freq_mhz: float = DEFAULT_FREQ_MHZ) -> float:
    """Median E2E residual ``kernel_e2e - maint - conv_span`` in cycles.

    Fit over full-E2E calibration rows (rows carrying all of maint/conv_span/
    kernel_e2e).  Empirically this is ~0 (a sub-cycle measurement window), so the
    serial ledger is essentially exact; we keep it as a calibrated term rather
    than assuming zero.
    """

    residuals: list[float] = []
    for row in rows:
        ke = _ms_cycles(row.get("median_kernel_e2e_ms"), freq_mhz)
        mm = _ms_cycles(row.get("median_maint_ms"), freq_mhz)
        cs = _ms_cycles(row.get("median_conv_span_ms"), freq_mhz)
        if None in (ke, mm, cs):
            continue
        residuals.append(ke - mm - cs)  # type: ignore[operator]
    if not residuals:
        return 0.0
    return statistics.median(residuals)


# ---------------------------------------------------------------------------
# E2E ledger
# ---------------------------------------------------------------------------

MAINT_DOMINANT_RATIO = 1.25
READER_DOMINANT_RATIO = 0.85
COMPUTE_TAIL_RATIO = 0.40


@dataclass(frozen=True)
class E2EInputs:
    """Everything needed to build one E2E ledger row.

    Actuals are measured cycles; ``*_pred`` come from the injected component
    models.  ``b_whatif_speedups`` maps a B-model what-if name to its speedup so
    the E2E what-ifs can re-use the Phase 4C B analysis.
    """

    group: str
    role: str
    case: str
    sweep: str
    batch_edges: float
    jitter_pct: float
    B_actual: float
    R_actual: float
    D_span_actual: float
    kernel_e2e_actual: float
    B_pred: float
    R_pred: float
    D_span_pred: float
    overhead_model: float
    b_whatif_speedups: dict[str, float] = field(default_factory=dict)
    d_whatif_cycles: dict[str, float] = field(default_factory=dict)


def bottleneck(b: float, r: float, d_span: float, d_tail: float) -> str:
    if d_span <= 0.0:
        return "maintenance_dominant" if b > 0 else "balanced"
    if b >= d_span * MAINT_DOMINANT_RATIO:
        return "maintenance_dominant"
    if r >= d_span * READER_DOMINANT_RATIO:
        return "reader_dominant"
    if d_tail >= d_span * COMPUTE_TAIL_RATIO:
        return "compute_tail_dominant"
    return "balanced"


def _speedup(base: float, new: float) -> float:
    return base / new if new > 0.0 else 1.0


def build_e2e_prediction(inp: E2EInputs) -> dict[str, Any]:
    b_act, r_act, d_act, ke_act = (
        inp.B_actual,
        inp.R_actual,
        inp.D_span_actual,
        inp.kernel_e2e_actual,
    )
    b_pred, r_pred, d_pred, overhead = (
        inp.B_pred,
        inp.R_pred,
        inp.D_span_pred,
        inp.overhead_model,
    )

    d_tail_act = max(0.0, d_act - r_act)
    d_tail_pred = max(0.0, d_pred - r_pred)

    no_overhead_pred = b_pred + d_pred
    serial_pred = b_pred + d_pred + overhead
    ideal_bd_overlap_pred = max(b_pred, d_pred) + overhead

    overhead_actual = ke_act - b_act - d_act
    overhead_note = "overlap_or_measurement_window" if overhead_actual < 0.0 else ""

    b_err = _pct(b_pred, b_act)
    r_err = _pct(r_pred, r_act)
    d_err = _pct(d_pred, d_act)
    serial_err = _pct(serial_pred, ke_act)

    # --- what-ifs (speedups relative to the modeled serial prediction) --------
    b_filter = inp.b_whatif_speedups.get("halve_repeated_filter_scans", 1.0)
    b_write = inp.b_whatif_speedups.get("halve_level_write_path", 1.0)
    new_b_filter = b_pred / b_filter if b_filter > 0 else b_pred
    new_b_write = b_pred / b_write if b_write > 0 else b_pred
    serial_filter = new_b_filter + d_pred + overhead
    serial_write = new_b_write + d_pred + overhead

    # Halving the reader only reduces the reader-covered part of the D span.
    new_d_span_reader = max(d_tail_pred, d_pred - 0.5 * r_pred)
    serial_reader = b_pred + new_d_span_reader + overhead

    whatifs: dict[str, float] = {
        "whatif_halve_b_repeated_scans_speedup": _speedup(serial_pred, serial_filter),
        "whatif_halve_b_level_write_path_speedup": _speedup(serial_pred, serial_write),
        "whatif_halve_reader_time_speedup": _speedup(serial_pred, serial_reader),
        "whatif_ideal_bd_overlap_speedup": _speedup(serial_pred, ideal_bd_overlap_pred),
    }
    # Optional D-driven what-ifs when the D model supplied alternative spans.
    for name, key in (
        ("whatif_halve_d_full_tile_sweep_speedup", "full_sweep_half"),
        ("whatif_halve_d_replay_speedup", "replay_to_clipped"),
    ):
        alt_span = inp.d_whatif_cycles.get(key)
        if alt_span is not None:
            serial_alt = b_pred + min(d_pred, alt_span) + overhead
            whatifs[name] = _speedup(serial_pred, serial_alt)

    bottleneck_actual = bottleneck(b_act, r_act, d_act, d_tail_act)
    bottleneck_pred = bottleneck(b_pred, r_pred, d_pred, d_tail_pred)

    out: dict[str, Any] = {
        "group": inp.group,
        "role": inp.role,
        "case": inp.case,
        "sweep": inp.sweep,
        "B_actual_cycles": b_act,
        "B_pred_cycles": b_pred,
        "B_error_pct": b_err,
        "R_actual_cycles": r_act,
        "R_pred_cycles": r_pred,
        "R_error_pct": r_err,
        "D_span_actual_cycles": d_act,
        "D_span_pred_cycles": d_pred,
        "D_span_error_pct": d_err,
        "D_tail_actual_cycles": d_tail_act,
        "D_tail_pred_cycles": d_tail_pred,
        "kernel_e2e_actual_cycles": ke_act,
        "no_overhead_pred_cycles": no_overhead_pred,
        "serial_pred_cycles": serial_pred,
        "serial_error_pct": serial_err,
        "ideal_bd_overlap_pred_cycles": ideal_bd_overlap_pred,
        "overhead_actual_cycles": overhead_actual,
        "overhead_model_cycles": overhead,
        "overhead_note": overhead_note,
        "bottleneck_actual": bottleneck_actual,
        "bottleneck_pred": bottleneck_pred,
        "trusted_status": classify_trust(abs(serial_err)),
        "evidence_note": _evidence_note(inp),
    }
    out.update(whatifs)
    return out


def _evidence_note(inp: E2EInputs) -> str:
    notes: list[str] = []
    if inp.batch_edges and inp.batch_edges < TINY_EDGE_THRESHOLD:
        notes.append(f"tiny_case_edges_lt_{TINY_EDGE_THRESHOLD}")
    if inp.jitter_pct > HIGH_JITTER_PCT:
        notes.append(f"high_jitter_gt_{HIGH_JITTER_PCT:g}pct")
    if inp.role.endswith("holdout") or inp.role == "holdout":
        notes.append("holdout")
    return ";".join(notes)


# ---------------------------------------------------------------------------
# CSV / summary shaping
# ---------------------------------------------------------------------------

E2E_PREDICTION_FIELD_ORDER = [
    "group",
    "role",
    "case",
    "sweep",
    "B_actual_cycles",
    "B_pred_cycles",
    "B_error_pct",
    "R_actual_cycles",
    "R_pred_cycles",
    "R_error_pct",
    "D_span_actual_cycles",
    "D_span_pred_cycles",
    "D_span_error_pct",
    "D_tail_actual_cycles",
    "D_tail_pred_cycles",
    "kernel_e2e_actual_cycles",
    "no_overhead_pred_cycles",
    "serial_pred_cycles",
    "serial_error_pct",
    "ideal_bd_overlap_pred_cycles",
    "overhead_actual_cycles",
    "overhead_model_cycles",
    "overhead_note",
    "bottleneck_actual",
    "bottleneck_pred",
    "trusted_status",
    "evidence_note",
    "whatif_halve_b_repeated_scans_speedup",
    "whatif_halve_b_level_write_path_speedup",
    "whatif_halve_reader_time_speedup",
    "whatif_ideal_bd_overlap_speedup",
    "whatif_halve_d_full_tile_sweep_speedup",
    "whatif_halve_d_replay_speedup",
]

E2E_GROUP_SUMMARY_FIELD_ORDER = [
    "validation_kind",
    "target",
    "group",
    "role",
    "cases",
    "median_abs_error_pct",
    "max_abs_error_pct",
    "trusted",
    "borderline",
    "untrusted",
]


def e2e_prediction_field_order() -> list[str]:
    return list(E2E_PREDICTION_FIELD_ORDER)


def e2e_group_summary(
    predictions: list[dict[str, Any]],
    extra_component_rows: list[dict[str, Any]] | None = None,
) -> list[dict[str, Any]]:
    """Summarize E2E and component validation.

    For each E2E group we emit one summary row per aligned target (B, R,
    D_span, serial).  ``extra_component_rows`` lets the caller append
    already-computed component-validation summaries (e.g. the B model on its own
    B evidence, or the D span model on D evidence).
    """

    summaries: list[dict[str, Any]] = []
    grouped: dict[tuple[str, str], list[dict[str, Any]]] = {}
    for prediction in predictions:
        grouped.setdefault((prediction["role"], prediction["group"]), []).append(prediction)

    targets = [
        ("B", "B_error_pct"),
        ("R", "R_error_pct"),
        ("D_span", "D_span_error_pct"),
        ("serial", "serial_error_pct"),
    ]
    for (role, group), preds in sorted(grouped.items()):
        for target, error_key in targets:
            abs_errors = [abs(float(p[error_key])) for p in preds if p.get(error_key) is not None]
            if not abs_errors:
                continue
            statuses = [_status(err) for err in abs_errors]
            summaries.append(
                {
                    "validation_kind": "e2e",
                    "target": target,
                    "group": group,
                    "role": role,
                    "cases": len(abs_errors),
                    "median_abs_error_pct": statistics.median(abs_errors),
                    "max_abs_error_pct": max(abs_errors),
                    "trusted": statuses.count("trusted"),
                    "borderline": statuses.count("borderline"),
                    "untrusted": statuses.count("untrusted"),
                }
            )
    if extra_component_rows:
        summaries.extend(extra_component_rows)
    return summaries


def component_summary_row(
    target: str,
    group: str,
    role: str,
    abs_errors: list[float],
) -> dict[str, Any]:
    statuses = [_status(err) for err in abs_errors]
    return {
        "validation_kind": "component",
        "target": target,
        "group": group,
        "role": role,
        "cases": len(abs_errors),
        "median_abs_error_pct": statistics.median(abs_errors) if abs_errors else "",
        "max_abs_error_pct": max(abs_errors) if abs_errors else "",
        "trusted": statuses.count("trusted"),
        "borderline": statuses.count("borderline"),
        "untrusted": statuses.count("untrusted"),
    }


def reader_model_to_dict(model: ReaderModel) -> dict[str, Any]:
    return {
        "target": "median_reader_ms",
        "target_units": "cycles",
        "backend": "standardized_ols_v1",
        "intercept": model.intercept,
        "features": model.features,
        "means": model.means,
        "stds": model.stds,
        "standardized_coefficients": model.coefficients,
    }


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _status(abs_error_pct: float) -> str:
    if abs_error_pct <= TRUSTED_MAX_ABS_PCT:
        return "trusted"
    if abs_error_pct <= BORDERLINE_MAX_ABS_PCT:
        return "borderline"
    return "untrusted"


def _pct(pred: float, actual: float) -> float:
    return (pred - actual) / actual * 100.0 if actual else 0.0


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


def _reader_cycles(row: dict[str, Any], freq_mhz: float) -> float | None:
    return _ms_cycles(row.get("median_reader_ms"), freq_mhz)
