"""E2E timing bridge — feed the simulator's structural features into the
already-calibrated component models to emit HW-matching per-stage E2E timing.

This is the "4a" bridge described in ``docs/history/early_models/e2e_bridge_20260720.md``: it does not
re-fit any of the validated science and it does not mechanize anything. It wires
the mechanistic ``SpineV0Simulator`` (which emits structural ``dstage_tile_*``
features but only Phase-2-era timing) to the HW-validated component models:

    B      -> Phase 4C maintenance model (bstage)
    D_span -> D-stage tile component model (dstage component + corrections)
    R      -> Phase 5A reader model (reader v2), diagnostic only
    serial -> B_pred + D_span_pred + overhead      (R NOT added in)

The enabling trick: a simulator run is written out in the *exact* HW evidence
CSV shape (``summary.csv`` + ``tile_schedule.csv``) and then loaded back through
the same loaders the hardware analysis uses. Because the sim's tile schedule is
produced by the same tiling algorithm as the hardware host, its structural
features match the HW rows exactly (verified in the Phase 5A feasibility check),
so a sim-driven prediction equals the HW-feature-driven prediction and the
sim-vs-HW error is pure component-model error.

This module is the integration layer, so (unlike ``e2e.py``) it intentionally
imports the D-span predictor and tile-feature loaders that live under
``scripts/``. ``models/spine.py`` imports this lazily, only when E2E emission is
opted into, so the default simulator import stays scripts-free.
"""

from __future__ import annotations

import csv
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable

from .bstage import CaseRecord, fit_component_model, load_default_evidence
from .e2e import E2EInputs, build_e2e_prediction, compute_overhead_model
from .maintenance import DEFAULT_FREQ_MHZ
from .reader import (
    ReaderComponentModel,
    fit_reader_component_model,
    load_reader_rows,
)

# Columns emitted into the HW-format sim evidence dir.
_TILE_COLUMNS = [
    "case",
    "sweep",
    "repeat",
    "partition",
    "tile",
    "tile_begin",
    "tile_end",
    "tile_size",
    "tile_work",
    "path",
    "fallback_used",
    "nonempty",
    "clipped_ranges",
    "gathered_vertex_words",
    "swept_vertex_words",
    "scattered_vertex_words",
]

_SUMMARY_PLACEHOLDER_MS = 0.0  # inert: predictions never read the actual-ms fields.


# ---------------------------------------------------------------------------
# Simulator result -> HW-format evidence rows
# ---------------------------------------------------------------------------


def _num(value: Any) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0


def sim_result_to_evidence(
    result: dict[str, Any], case: str, sweep: str
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    """Map one ``SpineV0Simulator._result()`` dict to a HW-format summary row and
    tile-schedule rows. Actual-ms fields are placeholders (predictions never read
    them); every structural feature comes from the sim's ``dstage_tile_*`` output.
    """

    summary_row = {
        "case": case,
        "sweep": sweep,
        "repeats": 1,
        "successful_repeats": 1,
        "median_active_records": _num(result.get("dstage_tile_active_records")),
        "median_active_sources": _num(result.get("dstage_tile_active_sources")),
        "median_touched_tiles": _num(result.get("dstage_tile_touched_tiles")),
        "median_traversed_edges": _num(result.get("dstage_tile_traversed_edges")),
        "median_input_edges": _num(result.get("edges")),
        "median_target_level": 0.0,
        "median_maint_ms": _SUMMARY_PLACEHOLDER_MS,
        "median_reader_ms": _SUMMARY_PLACEHOLDER_MS,
        "median_conv_span_ms": _SUMMARY_PLACEHOLDER_MS,
        "median_kernel_e2e_ms": _SUMMARY_PLACEHOLDER_MS,
        "conv_ms_jitter_pct": 0.0,
    }

    tile_rows: list[dict[str, Any]] = []
    for entry in result.get("dstage_tile_schedule", []):
        row = {key: entry.get(key) for key in _TILE_COLUMNS if key in entry}
        row["case"] = case
        row["sweep"] = sweep
        row["repeat"] = 1
        tile_rows.append(row)
    return summary_row, tile_rows


def write_sim_evidence_dir(
    rows: list[tuple[dict[str, Any], list[dict[str, Any]]]], out_dir: str | Path
) -> Path:
    """Write ``summary.csv`` + ``tile_schedule.csv`` (HW evidence shape) so the
    existing loaders read simulator output unchanged."""

    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    summary_rows = [summary for summary, _ in rows]
    tile_rows = [tile for _, tiles in rows for tile in tiles]

    _write_csv(out_dir / "summary.csv", summary_rows)
    _write_csv(out_dir / "tile_schedule.csv", tile_rows or [{c: "" for c in _TILE_COLUMNS}])
    return out_dir


def _write_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    fieldnames: list[str] = []
    for row in rows:
        for key in row:
            if key not in fieldnames:
                fieldnames.append(key)
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames, extrasaction="ignore")
        writer.writeheader()
        for row in rows:
            writer.writerow(row)


# ---------------------------------------------------------------------------
# Model bundle
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class BridgeModels:
    b_model: Any
    reader_model: ReaderComponentModel
    dspan_predict: Callable[[dict[str, Any]], dict[str, float]]
    overhead_cycles: float
    freq_mhz: float = DEFAULT_FREQ_MHZ

    @classmethod
    def load(cls, root: str | Path = ".", freq_mhz: float = DEFAULT_FREQ_MHZ) -> "BridgeModels":
        """Fit/load the four sub-models once, reusing the exact calibration the
        hardware analysis uses. Imports the D-span predictor and reader/overhead
        calibration from ``scripts/`` (this is the integration layer)."""

        import sys

        root = Path(root)
        if str(root) not in sys.path:
            sys.path.insert(0, str(root))

        from scripts.analyze_dstage_component_model import (  # noqa: E402
            DatasetSpec,
            load_labeled_dataset,
        )
        from scripts.analyze_e2e_component_model import (  # noqa: E402
            DEFAULT_BASE_MODEL_FIT,
            DEFAULT_OVERHEAD_DIRS,
            build_dspan_predictor,
        )
        from scripts.analyze_reader_component_model import (  # noqa: E402
            DEFAULT_CALIBRATION_DIRS as READER_CAL_DIRS,
        )

        b_model = fit_component_model(load_default_evidence(root=root, freq_mhz=freq_mhz), freq_mhz=freq_mhz)

        reader_rows: list[dict[str, Any]] = []
        for raw in READER_CAL_DIRS:
            path = Path(raw)
            if not path.is_absolute():
                path = root / path
            if path.exists():
                reader_rows.extend(load_reader_rows(path))
        reader_model = fit_reader_component_model(reader_rows, freq_mhz=freq_mhz)

        dspan_predict, _coeffs, _backend = build_dspan_predictor(DEFAULT_BASE_MODEL_FIT, freq_mhz)

        overhead_rows = [
            row
            for path in DEFAULT_OVERHEAD_DIRS
            for row in load_labeled_dataset(DatasetSpec("overhead_cal", "calibration", path))
        ]
        overhead = compute_overhead_model(overhead_rows, freq_mhz=freq_mhz)

        return cls(
            b_model=b_model,
            reader_model=reader_model,
            dspan_predict=dspan_predict,
            overhead_cycles=overhead,
            freq_mhz=freq_mhz,
        )


# ---------------------------------------------------------------------------
# Prediction
# ---------------------------------------------------------------------------


def _b_record(reader_row: dict[str, Any], case: str, sweep: str) -> CaseRecord:
    """Build a maintenance CaseRecord for a reader-microbench-style store.

    These are single-batch L0 stores: ``batch_edges`` = the traversed input
    edges, ``active_partitions`` = distinct partitions the tiles land on.
    """

    edges = int(_num(reader_row.get("median_traversed_edges") or reader_row.get("traversed_edges")))
    active_parts = int(_num(reader_row.get("tile_partition_count")) or 1)
    source_count = int(_num(reader_row.get("median_active_records")) or 1)
    return CaseRecord(
        group="sim",
        role="sim",
        case=case,
        mode="l0_store",
        target_level=0,
        batch_edges=edges,
        active_partitions=max(1, active_parts),
        source_count=max(1, source_count),
        pages_epoch_stamped=float(active_parts),
        actual_cycles=0.0,
        jitter_pct=0.0,
    )


def predict_e2e(
    models: BridgeModels,
    reader_row: dict[str, Any],
    dstage_row: dict[str, Any],
    case: str,
    sweep: str,
    group: str = "sim",
    role: str = "sim",
    actuals: dict[str, float] | None = None,
) -> dict[str, Any]:
    """Assemble one E2E ledger row from the component models.

    ``actuals`` (optional) carries measured HW cycles keyed
    ``B_actual/R_actual/D_span_actual/kernel_e2e_actual`` for the sim-vs-HW
    comparison; when absent the actual columns are set equal to the predictions
    so error% is 0 (a pure prediction, no ground truth).
    """

    b_record = _b_record(reader_row, case, sweep)
    b_pred = float(models.b_model.predicted_cycles(b_record))
    r_pred = float(models.reader_model.predicted_cycles(reader_row))
    d_pred = float(models.dspan_predict(dstage_row)["d_span"])

    actuals = actuals or {}
    b_act = float(actuals.get("B_actual", b_pred))
    r_act = float(actuals.get("R_actual", r_pred))
    d_act = float(actuals.get("D_span_actual", d_pred))
    ke_act = float(actuals.get("kernel_e2e_actual", b_pred + d_pred + models.overhead_cycles))

    b_speedups = {
        name: entry["speedup"]
        for name, entry in models.b_model.predict(b_record)["whatifs"].items()
    }

    inp = E2EInputs(
        group=group,
        role=role,
        case=case,
        sweep=sweep,
        batch_edges=float(b_record.batch_edges),
        jitter_pct=0.0,
        B_actual=b_act,
        R_actual=r_act,
        D_span_actual=d_act,
        kernel_e2e_actual=ke_act,
        B_pred=b_pred,
        R_pred=r_pred,
        D_span_pred=d_pred,
        overhead_model=models.overhead_cycles,
        b_whatif_speedups=b_speedups,
    )
    return build_e2e_prediction(inp)


def predict_e2e_from_results(
    models: BridgeModels,
    cases: list[tuple[str, str, dict[str, Any]]],
    actuals_by_case: dict[str, dict[str, float]] | None = None,
) -> list[dict[str, Any]]:
    """Predict E2E for a batch of simulator results.

    ``cases`` = list of ``(case, sweep, sim_result)``. Writes the results to a
    temporary HW-format evidence dir and reloads them through the exact HW
    loaders (guaranteeing identical feature extraction), then predicts each.
    """

    import sys

    if str(Path.cwd()) not in sys.path:
        sys.path.insert(0, str(Path.cwd()))
    from scripts.analyze_dstage_component_model import enrich_rows_with_tile_entries  # noqa: E402
    from scripts.analyze_hw_dstage_tile_timing import load_dataset  # noqa: E402

    actuals_by_case = actuals_by_case or {}
    evidence = [sim_result_to_evidence(result, case, sweep) for case, sweep, result in cases]

    with tempfile.TemporaryDirectory(prefix="sim_e2e_bridge_") as tmp:
        sim_dir = write_sim_evidence_dir(evidence, tmp)
        reader_by_case = {str(r["case"]): r for r in load_reader_rows(sim_dir)}
        dstage_by_case = {
            str(r["case"]): r for r in enrich_rows_with_tile_entries(load_dataset(sim_dir))
        }

        out: list[dict[str, Any]] = []
        for case, sweep, _ in cases:
            reader_row = reader_by_case.get(case)
            dstage_row = dstage_by_case.get(case)
            if reader_row is None or dstage_row is None:
                continue
            out.append(
                predict_e2e(
                    models,
                    reader_row,
                    dstage_row,
                    case=case,
                    sweep=sweep,
                    actuals=actuals_by_case.get(case),
                )
            )
    return out
