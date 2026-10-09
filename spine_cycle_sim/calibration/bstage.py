"""Phase 4C current-hardware B-stage / maintenance single-stage timing model.

Scope
-----
This module models the timing behaviour of the *current* HLS maintenance kernel
as it already exists on the deployed ``spine_partitioned_split_e2e.hw.xclbin``.
It does not modify the HLS kernel and does not require rebuilding the xclbin --
it is an analysis-level component model calibrated from existing synthetic HW
microbenchmark evidence and validated against holdout synthetic runs and
real / real-like Amazon slices.

Two maintenance paths are modelled separately:

L0 store path (``mode == "l0_store"``)
    Empirically the old model treated every L0 store as a 16-partition star,
    which massively over-predicts real one-partition slices.  We instead fit a
    four-term model over the calibration evidence::

        cycles = fixed
               + active_parts * c_part
               + edges        * c_edge
               + edges * active_parts * c_edge_part

    * ``fixed``        -- kernel/dispatch/metadata fixed cost.
    * ``c_part``       -- per active-partition setup (epoch/page metadata).
    * ``c_edge``       -- common per-edge work: the single hot/cold input scan
      plus the 16-family pre-count scan (both independent of how many
      partitions actually receive edges).
    * ``c_edge_part``  -- the per active-partition, per-edge *composite* of the
      active-partition filter scan and the coalesced level write.  Each active
      partition re-scans ``num_edges`` to select its own family and writes its
      coalesced rows in the same pass, so filter and write cannot be split with
      the current evidence.  This term is therefore explicitly a composite.

Carry / cascade path (``mode == "carry"``)
    Reuses the existing structural counters and calibration constants
    (scan 145, payload/output edge 80, row cursor 130, refill stall 1) from
    :mod:`spine_cycle_sim.calibration.maintenance` and adds a single positive
    ``fixed_residual`` correction fitted from the calibration synthetic
    residuals.

See ``docs/history/early_models/bstage_phase4c_component_model_20260720.md`` for the full HLS action
mapping and reproduction commands.
"""

from __future__ import annotations

import statistics
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from .maintenance import (
    CALIBRATED_CARRY_PAYLOAD_OUTPUT_EDGE_CYCLES,
    CALIBRATED_CARRY_ROW_CURSOR_CYCLES,
    CALIBRATED_CARRY_SCAN_ITERATION_CYCLES,
    CALIBRATED_REFILL_STALL_CYCLES,
    DEFAULT_FREQ_MHZ,
    ExperimentSpec,
    _estimate_structural_event,
    _solve_linear,
    parse_hw_maintenance_output,
    read_rows_csv,
)

# ---------------------------------------------------------------------------
# Structural constants
# ---------------------------------------------------------------------------

FAMILY_COUNT = 16
#: The shared L0/carry edge scan is composed of one hot/cold input pass plus one
#: pre-count / family-filter pass per family.  We attribute the fitted per-edge
#: term across these ``1 + FAMILY_COUNT`` passes when producing an explanatory
#: component breakdown.  This 1:16 split is an interpretive apportionment of a
#: single fitted coefficient, *not* an independent hardware counter.
L0_SCAN_TOTAL_PASSES = 1 + FAMILY_COUNT

#: Trust classification thresholds on absolute percentage error.
TRUSTED_MAX_ABS_PCT = 15.0
BORDERLINE_MAX_ABS_PCT = 30.0

#: Cases below this edge count, or with high measurement jitter, are dominated
#: by fixed cost / timer noise and are flagged in ``evidence_note``.
TINY_EDGE_THRESHOLD = 512
HIGH_JITTER_PCT = 5.0

COMPONENT_ORDER = [
    "fixed_dispatch",
    "hot_cold_input_scan",
    "family_precount_scan",
    "active_partition_filter_and_level_write",
    "cursor_row_walk",
    "payload_merge_and_level_write",
    "refill_stall",
    "page_epoch_or_metadata_update",
    "overflow_or_fallback_diagnostic",
]

WHATIF_ORDER = [
    "halve_repeated_filter_scans",
    "halve_level_write_path",
    "l0_single_active_partition",
]

#: Default evidence directories (see task brief / docs).
DEFAULT_EVIDENCE = {
    "phase2b": {
        "path": "results/phase4c_bstage_phase2b_current_hw_20260720_111449",
        "role": "calibration",
        "kind": "synthetic",
    },
    "phase4c_onepart": {
        "path": "results/phase4c_bstage_partition_spread_current_hw_20260720_114845",
        "role": "calibration",
        "kind": "synthetic",
    },
    "phase2d_holdout": {
        "path": "results/phase4c_bstage_phase2d_holdout_current_hw_20260720_111746",
        "role": "holdout",
        "kind": "synthetic",
    },
    "phase4a_amazon_real": {
        "path": "results/phase4a_amazon_exact_slices_hw_20260719_224034",
        "role": "holdout",
        "kind": "real_slice",
    },
}


# ---------------------------------------------------------------------------
# Data records
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class CaseRecord:
    """A normalized, per-case evidence row used for fitting and validation."""

    group: str
    role: str
    case: str
    mode: str
    target_level: int
    batch_edges: int
    active_partitions: int
    source_count: int
    pages_epoch_stamped: float
    actual_cycles: float
    jitter_pct: float
    evidence_dir: str = ""


@dataclass(frozen=True)
class L0ComponentModel:
    fixed: float
    c_part: float
    c_edge: float
    c_edge_part: float

    def total(self, batch_edges: float, active_partitions: float) -> float:
        return (
            self.fixed
            + self.c_part * active_partitions
            + self.c_edge * batch_edges
            + self.c_edge_part * batch_edges * active_partitions
        )


@dataclass(frozen=True)
class CarryComponentModel:
    fixed_residual: float
    scan_iteration_cycles: int = CALIBRATED_CARRY_SCAN_ITERATION_CYCLES
    payload_output_edge_cycles: int = CALIBRATED_CARRY_PAYLOAD_OUTPUT_EDGE_CYCLES
    row_cursor_cycles: int = CALIBRATED_CARRY_ROW_CURSOR_CYCLES
    refill_stall_cycles: int = CALIBRATED_REFILL_STALL_CYCLES


@dataclass(frozen=True)
class BStageComponentModel:
    l0: L0ComponentModel
    carry: CarryComponentModel
    freq_mhz: float = DEFAULT_FREQ_MHZ
    calibration: dict[str, Any] = field(default_factory=dict)

    # -- component predictions -------------------------------------------------

    def components(self, record: CaseRecord) -> dict[str, float]:
        if record.mode == "carry":
            return self._carry_components(record)
        return self._l0_components(record)

    def _l0_components(self, record: CaseRecord) -> dict[str, float]:
        edges = float(record.batch_edges)
        parts = float(record.active_partitions)
        scan = self.l0.c_edge * edges
        hot_cold = scan / L0_SCAN_TOTAL_PASSES
        family = scan - hot_cold
        filter_write = self.l0.c_edge_part * edges * parts
        page_epoch = self.l0.c_part * parts
        components = _zero_components()
        components["fixed_dispatch"] = self.l0.fixed
        components["hot_cold_input_scan"] = hot_cold
        components["family_precount_scan"] = family
        components["active_partition_filter_and_level_write"] = filter_write
        components["page_epoch_or_metadata_update"] = page_epoch
        return components

    def _carry_components(self, record: CaseRecord) -> dict[str, float]:
        spec = ExperimentSpec(
            case=record.case,
            sweep="",
            mode="carry",
            args=(),
            target_level=int(record.target_level),
            batch_edges=int(record.batch_edges),
            source_count=max(1, int(record.source_count)),
            expected_path="cascade",
        )
        event = _estimate_structural_event(spec)
        scan = float(event["calibrated_scan_cycles"])
        hot_cold = scan / L0_SCAN_TOTAL_PASSES
        family = scan - hot_cold
        output_edges = float(event["output_edges"])
        old_edges = output_edges - float(record.batch_edges)
        merge = (old_edges + output_edges) * self.carry.payload_output_edge_cycles
        row_cursor = float(event["rows_entered"]) * self.carry.row_cursor_cycles
        refill = float(event["refill_stalls"]) * self.carry.refill_stall_cycles
        # The remaining structural budget is the page/metadata write-back.  We
        # derive it by difference so the component sum matches the structural
        # estimate exactly.
        page_meta = float(event["estimated_cycles"]) - scan - merge - row_cursor - refill
        components = _zero_components()
        components["fixed_dispatch"] = self.carry.fixed_residual
        components["hot_cold_input_scan"] = hot_cold
        components["family_precount_scan"] = family
        components["cursor_row_walk"] = row_cursor
        components["payload_merge_and_level_write"] = merge
        components["refill_stall"] = refill
        components["page_epoch_or_metadata_update"] = page_meta
        return components

    def predicted_cycles(self, record: CaseRecord) -> float:
        return sum(self.components(record).values())

    # -- what-if analysis ------------------------------------------------------

    def whatifs(self, record: CaseRecord) -> dict[str, dict[str, float]]:
        components = self.components(record)
        total = sum(components.values())
        out: dict[str, dict[str, float]] = {}

        # 1. Halve repeated sorted-edge / family-filter scans.
        save_filter = 0.5 * components["family_precount_scan"]
        out["halve_repeated_filter_scans"] = _whatif_entry(total, save_filter)

        # 2. Halve the active-filter + level-write composite (L0) or the carry
        #    payload-merge + level-write path.
        save_write = 0.5 * (
            components["active_partition_filter_and_level_write"]
            + components["payload_merge_and_level_write"]
        )
        out["halve_level_write_path"] = _whatif_entry(total, save_write)

        # 3. (L0 only) collapse a 16-partition star into a single active
        #    partition write.  For carry / already-single-partition cases this is
        #    a no-op (speedup 1.0).
        if record.mode != "carry" and record.active_partitions > 1:
            single = self._l0_components(
                CaseRecord(
                    group=record.group,
                    role=record.role,
                    case=record.case,
                    mode=record.mode,
                    target_level=record.target_level,
                    batch_edges=record.batch_edges,
                    active_partitions=1,
                    source_count=record.source_count,
                    pages_epoch_stamped=record.pages_epoch_stamped,
                    actual_cycles=record.actual_cycles,
                    jitter_pct=record.jitter_pct,
                )
            )
            single_total = sum(single.values())
            out["l0_single_active_partition"] = {
                "cycles": single_total,
                "speedup": (total / single_total) if single_total > 0 else 1.0,
            }
        else:
            out["l0_single_active_partition"] = {"cycles": total, "speedup": 1.0}
        return out

    # -- full per-case prediction ---------------------------------------------

    def predict(self, record: CaseRecord) -> dict[str, Any]:
        components = self.components(record)
        predicted = sum(components.values())
        actual = float(record.actual_cycles)
        error_pct = ((predicted - actual) / actual * 100.0) if actual else 0.0
        abs_error_pct = abs(error_pct)
        top_component = max(components, key=lambda name: components[name])
        result: dict[str, Any] = {
            "group": record.group,
            "role": record.role,
            "case": record.case,
            "mode": record.mode,
            "target_level": record.target_level,
            "batch_edges": record.batch_edges,
            "active_partitions": record.active_partitions,
            "pages_epoch_stamped": record.pages_epoch_stamped,
            "actual_cycles": actual,
            "predicted_cycles": predicted,
            "error_pct": error_pct,
            "abs_error_pct": abs_error_pct,
            "trusted_status": classify_trust(abs_error_pct),
            "evidence_note": evidence_note(record),
            "top_component": top_component,
            "top_component_cycles": components[top_component],
            "components": components,
            "whatifs": self.whatifs(record),
        }
        return result


# ---------------------------------------------------------------------------
# Fitting
# ---------------------------------------------------------------------------


def fit_l0_model(records: list[CaseRecord]) -> L0ComponentModel:
    """Least-squares fit of the four L0 terms over ``l0_store`` records."""

    samples = [r for r in records if r.mode == "l0_store"]
    if len(samples) < 4:
        raise ValueError("need at least 4 l0_store records to fit the L0 model")
    design = [
        [1.0, float(r.active_partitions), float(r.batch_edges),
         float(r.batch_edges) * float(r.active_partitions)]
        for r in samples
    ]
    targets = [float(r.actual_cycles) for r in samples]
    beta = _least_squares(design, targets)
    return L0ComponentModel(fixed=beta[0], c_part=beta[1], c_edge=beta[2], c_edge_part=beta[3])


def fit_carry_residual(records: list[CaseRecord]) -> float:
    """Fit a positive fixed residual from the carry calibration residuals."""

    residuals: list[float] = []
    for record in records:
        if record.mode != "carry":
            continue
        spec = ExperimentSpec(
            case=record.case,
            sweep="",
            mode="carry",
            args=(),
            target_level=int(record.target_level),
            batch_edges=int(record.batch_edges),
            source_count=max(1, int(record.source_count)),
            expected_path="cascade",
        )
        estimated = float(_estimate_structural_event(spec)["estimated_cycles"])
        residuals.append(float(record.actual_cycles) - estimated)
    if not residuals:
        return 0.0
    # A positive median keeps the correction a genuine additive fixed cost.
    return max(0.0, statistics.median(residuals))


def fit_component_model(
    records: list[CaseRecord],
    freq_mhz: float = DEFAULT_FREQ_MHZ,
) -> BStageComponentModel:
    """Fit the full B-stage component model from calibration records."""

    calibration = [r for r in records if r.role == "calibration"]
    if not calibration:
        raise ValueError("no calibration records supplied")
    l0 = fit_l0_model([r for r in calibration if r.mode == "l0_store"])
    carry_residual = fit_carry_residual([r for r in calibration if r.mode == "carry"])
    model = BStageComponentModel(
        l0=l0,
        carry=CarryComponentModel(fixed_residual=carry_residual),
        freq_mhz=freq_mhz,
    )
    model.calibration.update(_calibration_metrics(model, calibration))
    return model


def _calibration_metrics(
    model: BStageComponentModel, calibration: list[CaseRecord]
) -> dict[str, Any]:
    l0_errors = [
        abs(model.predict(r)["error_pct"]) for r in calibration if r.mode == "l0_store"
    ]
    carry_errors = [
        abs(model.predict(r)["error_pct"]) for r in calibration if r.mode == "carry"
    ]
    metrics: dict[str, Any] = {
        "l0_samples": sum(1 for r in calibration if r.mode == "l0_store"),
        "carry_samples": sum(1 for r in calibration if r.mode == "carry"),
    }
    if l0_errors:
        metrics["l0_median_abs_pct_error"] = statistics.median(l0_errors)
        metrics["l0_max_abs_pct_error"] = max(l0_errors)
    if carry_errors:
        metrics["carry_median_abs_pct_error"] = statistics.median(carry_errors)
        metrics["carry_max_abs_pct_error"] = max(carry_errors)
    return metrics


# ---------------------------------------------------------------------------
# Classification helpers
# ---------------------------------------------------------------------------


def classify_trust(abs_error_pct: float) -> str:
    if abs_error_pct <= TRUSTED_MAX_ABS_PCT:
        return "trusted"
    if abs_error_pct <= BORDERLINE_MAX_ABS_PCT:
        return "borderline"
    return "untrusted"


def evidence_note(record: CaseRecord) -> str:
    notes: list[str] = []
    if record.batch_edges < TINY_EDGE_THRESHOLD:
        notes.append(f"tiny_case_edges_lt_{TINY_EDGE_THRESHOLD}")
    if record.jitter_pct > HIGH_JITTER_PCT:
        notes.append(f"high_jitter_maint_ms_gt_{HIGH_JITTER_PCT:g}pct")
    if record.role == "holdout":
        notes.append("holdout")
    return ";".join(notes)


# ---------------------------------------------------------------------------
# Evidence loading
# ---------------------------------------------------------------------------


def load_synthetic_records(
    summary_path: str | Path,
    group: str,
    role: str,
    freq_mhz: float = DEFAULT_FREQ_MHZ,
) -> list[CaseRecord]:
    """Load an aggregated synthetic ``summary.csv`` (phase2b/phase2d/onepart)."""

    summary_path = Path(summary_path)
    rows = read_rows_csv(summary_path)
    records: list[CaseRecord] = []
    for row in rows:
        mode = str(row.get("mode", ""))
        actual = _num(row.get("median_hw_cycles"))
        if actual is None:
            continue
        batch_edges = int(_num(row.get("batch_edges")) or 0)
        if mode == "l0_store":
            active = int(_num(row.get("l0_partitions_written_median")) or 1)
            pages = _num(row.get("l0_pages_epoch_stamped_median")) or active
        else:
            active = int(_num(row.get("cold_page_ids_written_median")) or FAMILY_COUNT)
            pages = _num(row.get("cold_page_ids_written_median")) or FAMILY_COUNT
        records.append(
            CaseRecord(
                group=group,
                role=role,
                case=str(row.get("case", "")),
                mode=mode,
                target_level=int(_num(row.get("target_level")) or 0),
                batch_edges=batch_edges,
                active_partitions=active,
                source_count=int(_num(row.get("source_count")) or 1),
                pages_epoch_stamped=float(pages),
                actual_cycles=float(actual),
                jitter_pct=float(_num(row.get("maint_ms_jitter_pct")) or 0.0),
                evidence_dir=str(summary_path.parent),
            )
        )
    return records


def load_real_slice_records(
    evidence_dir: str | Path,
    group: str,
    role: str,
    freq_mhz: float = DEFAULT_FREQ_MHZ,
) -> list[CaseRecord]:
    """Load real / real-like exact Amazon slices (phase4a schema).

    Real exact slices are single-partition L0 stores by construction
    (``l0_partitions_written=1`` in the raw host output), so they exercise the
    one-partition L0 path.  Maintenance jitter is recomputed from the per-repeat
    ``runs.csv`` because the phase4a summary aggregates a different convergence
    schema.
    """

    evidence_dir = Path(evidence_dir)
    summary_rows = read_rows_csv(evidence_dir / "summary.csv")
    jitter = _real_slice_jitter(evidence_dir / "runs.csv")
    pages = _real_slice_pages_epoch(evidence_dir / "raw")
    records: list[CaseRecord] = []
    for row in summary_rows:
        maint_ms = _num(row.get("median_maint_ms"))
        if maint_ms is None:
            continue
        target_level = int(_num(row.get("median_target_level")) or 0)
        if target_level != 0:
            # Only L0 exact slices are in scope for the current-HW L0 model.
            continue
        case = str(row.get("case", ""))
        edges = int(_num(row.get("median_input_edges")) or 0)
        records.append(
            CaseRecord(
                group=group,
                role=role,
                case=case,
                mode="l0_store",
                target_level=0,
                batch_edges=edges,
                active_partitions=1,
                source_count=1,
                pages_epoch_stamped=float(pages.get(case, 1.0)),
                actual_cycles=float(maint_ms) * freq_mhz * 1000.0,
                jitter_pct=float(jitter.get(case, 0.0)),
                evidence_dir=str(evidence_dir),
            )
        )
    return records


def load_default_evidence(
    root: str | Path = ".",
    freq_mhz: float = DEFAULT_FREQ_MHZ,
    overrides: dict[str, str] | None = None,
) -> list[CaseRecord]:
    """Load the four default evidence groups from ``root``.

    ``overrides`` maps a group key in :data:`DEFAULT_EVIDENCE` to an alternate
    directory path.
    """

    root = Path(root)
    overrides = overrides or {}
    records: list[CaseRecord] = []
    for group, spec in DEFAULT_EVIDENCE.items():
        raw_path = overrides.get(group, spec["path"])
        path = Path(raw_path)
        if not path.is_absolute():
            path = root / path
        if not path.exists():
            raise FileNotFoundError(f"evidence dir for {group} not found: {path}")
        if spec["kind"] == "real_slice":
            records.extend(
                load_real_slice_records(path, group, spec["role"], freq_mhz=freq_mhz)
            )
        else:
            records.extend(
                load_synthetic_records(
                    path / "summary.csv", group, spec["role"], freq_mhz=freq_mhz
                )
            )
    return records


# ---------------------------------------------------------------------------
# CSV / summary shaping
# ---------------------------------------------------------------------------


def prediction_row(prediction: dict[str, Any]) -> dict[str, Any]:
    """Flatten a :meth:`BStageComponentModel.predict` result into a CSV row."""

    total = float(prediction["predicted_cycles"]) or 1.0
    row: dict[str, Any] = {
        key: prediction[key]
        for key in (
            "group",
            "role",
            "case",
            "mode",
            "target_level",
            "batch_edges",
            "active_partitions",
            "pages_epoch_stamped",
            "actual_cycles",
            "predicted_cycles",
            "error_pct",
            "abs_error_pct",
            "trusted_status",
            "evidence_note",
            "top_component",
            "top_component_cycles",
        )
    }
    components = prediction["components"]
    for name in COMPONENT_ORDER:
        cycles = float(components.get(name, 0.0))
        row[f"comp_{name}_cycles"] = cycles
        row[f"comp_{name}_share"] = cycles / total
    for name in WHATIF_ORDER:
        entry = prediction["whatifs"].get(name, {"cycles": total, "speedup": 1.0})
        row[f"whatif_{name}_cycles"] = entry["cycles"]
        row[f"whatif_{name}_speedup"] = entry["speedup"]
    return row


def prediction_field_order() -> list[str]:
    order = [
        "group",
        "role",
        "case",
        "mode",
        "target_level",
        "batch_edges",
        "active_partitions",
        "pages_epoch_stamped",
        "actual_cycles",
        "predicted_cycles",
        "error_pct",
        "abs_error_pct",
        "trusted_status",
        "evidence_note",
        "top_component",
        "top_component_cycles",
    ]
    for name in COMPONENT_ORDER:
        order.append(f"comp_{name}_cycles")
        order.append(f"comp_{name}_share")
    for name in WHATIF_ORDER:
        order.append(f"whatif_{name}_cycles")
        order.append(f"whatif_{name}_speedup")
    return order


def group_summary(predictions: list[dict[str, Any]]) -> list[dict[str, Any]]:
    grouped: dict[tuple[str, str, str], list[dict[str, Any]]] = {}
    for prediction in predictions:
        key = (prediction["role"], prediction["group"], prediction["mode"])
        grouped.setdefault(key, []).append(prediction)

    summaries: list[dict[str, Any]] = []
    for (role, group, mode), preds in sorted(grouped.items()):
        abs_errors = [float(p["abs_error_pct"]) for p in preds]
        statuses = [p["trusted_status"] for p in preds]
        summaries.append(
            {
                "role": role,
                "group": group,
                "mode": mode,
                "cases": len(preds),
                "median_abs_error_pct": statistics.median(abs_errors),
                "max_abs_error_pct": max(abs_errors),
                "trusted": statuses.count("trusted"),
                "borderline": statuses.count("borderline"),
                "untrusted": statuses.count("untrusted"),
                "median_actual_cycles": statistics.median(
                    float(p["actual_cycles"]) for p in preds
                ),
            }
        )
    return summaries


def group_summary_field_order() -> list[str]:
    return [
        "role",
        "group",
        "mode",
        "cases",
        "median_abs_error_pct",
        "max_abs_error_pct",
        "trusted",
        "borderline",
        "untrusted",
        "median_actual_cycles",
    ]


def model_to_dict(model: BStageComponentModel) -> dict[str, Any]:
    return {
        "freq_mhz": model.freq_mhz,
        "l0_model": {
            "form": "cycles = fixed + active_parts*c_part + edges*c_edge + edges*active_parts*c_edge_part",
            "fixed": model.l0.fixed,
            "c_part": model.l0.c_part,
            "c_edge": model.l0.c_edge,
            "c_edge_part": model.l0.c_edge_part,
        },
        "carry_model": {
            "form": "cycles = structural_estimate + fixed_residual",
            "fixed_residual": model.carry.fixed_residual,
            "scan_iteration_cycles": model.carry.scan_iteration_cycles,
            "payload_output_edge_cycles": model.carry.payload_output_edge_cycles,
            "row_cursor_cycles": model.carry.row_cursor_cycles,
            "refill_stall_cycles": model.carry.refill_stall_cycles,
        },
        "component_order": COMPONENT_ORDER,
        "whatif_order": WHATIF_ORDER,
        "l0_scan_split": {
            "total_passes": L0_SCAN_TOTAL_PASSES,
            "note": (
                "The edges*c_edge term is apportioned 1:16 into hot_cold_input_scan "
                "and family_precount_scan as an explanatory split of a single fitted "
                "coefficient; it is not an independent hardware counter."
            ),
        },
        "trust_thresholds": {
            "trusted_max_abs_pct": TRUSTED_MAX_ABS_PCT,
            "borderline_max_abs_pct": BORDERLINE_MAX_ABS_PCT,
        },
        "calibration": model.calibration,
    }


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _zero_components() -> dict[str, float]:
    return {name: 0.0 for name in COMPONENT_ORDER}


def _whatif_entry(total: float, savings: float) -> dict[str, float]:
    new_total = total - savings
    speedup = (total / new_total) if new_total > 0 else 1.0
    return {"cycles": new_total, "speedup": speedup}


def _least_squares(design: list[list[float]], targets: list[float]) -> list[float]:
    dim = len(design[0])
    xtx = [[0.0 for _ in range(dim)] for _ in range(dim)]
    xty = [0.0 for _ in range(dim)]
    for row, y in zip(design, targets):
        for i in range(dim):
            xty[i] += row[i] * y
            for j in range(dim):
                xtx[i][j] += row[i] * row[j]
    return _solve_linear(xtx, xty)


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


def _real_slice_jitter(runs_path: Path) -> dict[str, float]:
    if not runs_path.exists():
        return {}
    rows = read_rows_csv(runs_path)
    grouped: dict[str, list[float]] = {}
    for row in rows:
        if int(_num(row.get("returncode")) or 1) != 0:
            continue
        maint = _num(row.get("maint_ms"))
        if maint is None:
            continue
        grouped.setdefault(str(row.get("case", "")), []).append(maint)
    jitter: dict[str, float] = {}
    for case, values in grouped.items():
        median = statistics.median(values)
        if median:
            jitter[case] = (max(values) - min(values)) / median * 100.0
    return jitter


def _real_slice_pages_epoch(raw_root: Path) -> dict[str, float]:
    pages: dict[str, float] = {}
    if not raw_root.exists():
        return pages
    for case_dir in sorted(raw_root.iterdir()):
        if not case_dir.is_dir():
            continue
        values: list[float] = []
        for stdout_path in sorted(case_dir.glob("run_*.stdout")):
            parsed = parse_hw_maintenance_output(stdout_path.read_text(encoding="utf-8"))
            value = _num(parsed.get("l0_pages_epoch_stamped"))
            if value is not None:
                values.append(value)
        if values:
            pages[case_dir.name] = statistics.median(values)
    return pages
