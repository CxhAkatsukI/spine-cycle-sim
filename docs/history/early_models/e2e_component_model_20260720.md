# E2E Component Timing Model / Analysis Layer

_Date: 2026-07-20_

## 1. Goal

Compose the already-calibrated per-stage models into a single **end-to-end
(E2E) ledger** for kernel execution time, calibrated and validated against
existing real / synthetic hardware evidence, and emit per-case bottleneck
breakdowns and what-if estimates.

This is an HLS-structure-aware, evidence-calibrated model — **not** a full
AXI/HBM/stream cycle-accurate replay. It preserves the existing simulator's
logical structure and feature extraction and reuses the Phase 4C B-stage model
and the D-stage tile component model.

## 2. Scope and non-goals

- **No HLS changes, no xclbin rebuild.** Pure simulator-/analysis-side work.
- **Does not change `SpineV0Simulator.run()`** — this is an independent
  analysis layer (`spine_cycle_sim/calibration/e2e.py` +
  `scripts/analyze_e2e_component_model.py`).
- First version is an **E2E skeleton**: it does not yet model AXI outstanding
  transactions, stream backpressure, or HBM contention as first-class effects.
- Conclusions are only claimed for the evidence-covered structure and same-class
  workloads (real one-partition L0 Amazon slices and the synthetic D/B sweeps).
  No claim is made about arbitrary new graphs.

## 3. Execution model and ledger

The current measured execution is modeled as **serial**: maintenance (the
B-stage) completes, then the reader + convergence span (D) consumes the updated
state. This is what the evidence shows — across every real and synthetic
full-E2E slice, `kernel_e2e_ms ≈ maint_ms + conv_span_ms` with a near-zero
residual (median overhead ≈ **−490 cycles ≈ 0**, i.e. a sub-cycle measurement
window). We do **not** claim the hardware physically cannot overlap; only that
the current measured execution is modeled as serial unless dedicated overlap
evidence proves otherwise.

`median_conv_span_ms` already contains the reader span, so to avoid double
counting the main total is:

```
serial_pred = B_pred + D_span_pred + overhead_model        (NOT B + R + D_span)
```

The reader `R` is an internal **diagnostic sub-model of the D span**:

```
R      aligns to median_reader_ms
D_tail = max(0, D_span - R)     # compute/tail not covered by the reader,
                                # or reader/compute overlap not covered by reader
```

Overhead is a residual/fixed calibration term:

```
overhead_actual = kernel_e2e_actual - B_actual - D_span_actual
```

If `overhead_actual < 0` for a case it is flagged
`overlap_or_measurement_window` rather than interpreted as negative overhead.

Additional predicted totals emitted per case:

```
no_overhead_pred      = B_pred + D_span_pred
serial_pred           = B_pred + D_span_pred + overhead_model
ideal_bd_overlap_pred = max(B_pred, D_span_pred) + overhead_model
```

## 4. Sub-models and how they map to hardware stages

| Stage | Aligns to | Source | Notes |
|---|---|---|---|
| **B** (maintenance) | `median_maint_ms` | Phase 4C B-stage component model (`bstage.py`) | one-partition L0 store for real slices; `cycles = fixed + active_parts·c_part + edges·c_edge + edges·active_parts·c_edge_part` |
| **D_span** (reader + convergence) | `median_conv_span_ms` | D-stage tile component model (`analyze_dstage_component_model.py`, base fit `phase3c_full_partition_analysis_.../fit.json` + non-negative residual corrections) | reused as-is |
| **R** (reader) | `median_reader_ms` | reader sub-model fit in `e2e.py` | diagnostic decomposition of D_span |
| **overhead** | `kernel_e2e − maint − conv_span` | median residual over synthetic full-E2E rows | ≈ 0 |

### Reader (R) model

Standardized **unweighted** OLS (ordinary least squares) fitting
`median_reader_ms → cycles`. Features:

- `median_traversed_edges`, `tile_full_swept_words`, `tile_scattered_words`,
  `tile_fast_gathered_words`, `median_active_records`.

The reader streams traversed edges from HBM and sweeps/gathers/scatters vertex
words, so reader time scales with edge and word volume — **not** with the
maintenance partition structure. Unweighted OLS is used deliberately: reader
time spans several orders of magnitude across slices, and `1/target` weighting
collapses the fit onto the tiniest, noisiest cases (empirically producing ~99%
under-prediction on the large slices).

**R is close to conv_span for reader-dominant slices** — e.g. Amazon
`top4096` has `reader_ms ≈ 437.86`, `conv_span_ms ≈ 438.30` (`R/D_span ≈ 0.999`).
Many D-stage real slices are reader-dominant; the model and this document
preserve that interpretation. R is a diagnostic, so it carries larger error on
tiny cases than the main serial total does.

## 5. Reproduction

```bash
cd /home/chuxiao/spine-cycle-sim
OUT=results/e2e_component_model_$(date +%Y%m%d_%H%M%S)
python3 scripts/analyze_e2e_component_model.py --out-dir "$OUT"

python3 -m unittest tests.test_e2e_component_model
python3 -m unittest discover -s tests
```

### Evidence directories

| Purpose | Directory |
|---|---|
| Real exact E2E (primary validation) | `results/phase4a_amazon_exact_slices_hw_20260719_224034` |
| Real-like reader calibration | `results/phase3d_amazon_slices_hw_20260719_220659` |
| Overhead calibration (synthetic full-E2E) | `results/phase3c_full_partition_calibration_hw_20260719_175201`, `results/dstage_phase3a4_replay_calibration_hw_20260719_155924`, `results/phase3b_bottleneck_synthetic_hw_20260719_172739` |
| D-span base fit + corrections | `results/phase3c_full_partition_analysis_20260719_175848/fit.json` (+ D calibration dirs) |
| B component evidence | `results/phase4c_bstage_*` (phase2b, phase2d_holdout, partition_spread) + phase4a |

The four exact cases `{top512, top8192, densewin4096, stride512}` are used as
calibration (consistent with the D-stage model's exact-calibration split); the
remaining exact slices are holdout.

## 6. Output files

`scripts/analyze_e2e_component_model.py --out-dir <DIR>`:

- **`e2e_model.json`** — freq, serial execution note, ledger form, overhead
  cycles, reader model coefficients, D-span correction components, B-model
  coefficients, bottleneck rules, evidence manifest.
- **`e2e_predictions.csv`** — one row per real exact slice with the full ledger:
  `group, role, case, sweep`, per-stage `*_actual_cycles / *_pred_cycles /
  *_error_pct` for B/R/D_span, `D_tail_*`, `kernel_e2e_actual_cycles`,
  `no_overhead_pred / serial_pred / serial_error_pct / ideal_bd_overlap_pred`,
  `overhead_actual / overhead_model / overhead_note`, `bottleneck_actual /
  bottleneck_pred`, `trusted_status`, `evidence_note`, and the four required
  what-if speedups plus two optional D what-ifs.
- **`e2e_group_summary.csv`** — component validation (B / D_span / R on their own
  evidence) and end-to-end validation (B / R / D_span / serial on the exact
  slices), with median/max abs error and trusted/borderline/untrusted tallies.

Trust classification (on `serial_error_pct` for E2E rows): `≤15%` trusted,
`≤30%` borderline, `>30%` untrusted. Cases with `edges < 512` or high jitter are
flagged in `evidence_note`.

## 7. Validation results (`e2e_group_summary`)

End-to-end (real exact Amazon slices):

| target | role | cases | median abs err % | max abs err % |
|---|---|---|---|---|
| serial | calibration | 4 | 6.49 | 16.32 |
| serial | holdout | 8 | 12.62 | 23.35 |
| B | holdout | 8 | 1.45 | 27.84 |
| R | holdout | 8 | 18.84 | 100.0 |
| D_span | holdout | 8 | 13.23 | 23.51 |

Component validation:

| target | group | median abs err % |
|---|---|---|
| B | phase2b (calib) | 0.11 |
| B | phase2d_holdout | 0.09 |
| D_span | phase3c_holdout | 4.38 |
| D_span | phase3c_final | 3.79 |
| D_span | phase3b_broad | 5.86 |
| R | reader_calibration | 7.01 |

The E2E serial error is bounded by the D-span model (D_span is the dominant term
for these reader-heavy slices); B is a small, well-predicted fraction. R's large
per-case errors are confined to tiny slices (`top1`/`top8`, edges < 512) and are
flagged; R is a diagnostic and does not enter the serial total.

## 8. Bottleneck conclusions

Across the 12 real exact slices, the **measured** bottleneck is
`reader_dominant` for 11/12 (the one exception, `top1` at 10 edges, is
`compute_tail_dominant` — a fixed-cost-dominated tiny case). This is the
headline structural finding: real one-partition L0 Amazon slices are
**reader-dominant**, i.e. `conv_span` is essentially the reader streaming edges
from HBM, and maintenance is a small fraction of end-to-end time.

Bottleneck rules (applied to actual and predicted independently):

- `B ≥ 1.25 · D_span` → `maintenance_dominant`
- `R ≥ 0.85 · D_span` → `reader_dominant`
- `D_tail ≥ 0.40 · D_span` → `compute_tail_dominant`
- otherwise → `balanced`

## 9. What-if conclusions

Per-case speedups relative to the modeled serial time:

1. **`halve_b_repeated_scans`** / **`halve_b_level_write_path`** (reuse the
   Phase 4C B what-ifs): ~**1.01×** / ~**1.06–1.11×** on real slices — small,
   because B is a small fraction of a reader-dominant E2E.
2. **`halve_reader_time`** (halve R, reduce the reader-covered part of D_span):
   ~**1.82× median** on reader-dominant slices — the **largest single lever**.
3. **`ideal_b_d_overlap`** (`max(B_pred, D_span_pred) + overhead`): ~**1.15–1.47×**
   — the ceiling of hiding maintenance fully under the D span. Modest, again
   because B is small relative to D_span here.
4. Optional D what-ifs: `halve_d_full_tile_sweep` (~1.00–1.03×, few full-sweep
   tiles in these slices) and `halve_d_replay` (~1.4–1.9×).

Takeaway: for this workload class, the reader path is where end-to-end time is
spent, and B/overlap optimizations yield little at the E2E level.

## 10. Limitations

- **AXI outstanding / HBM contention / stream backpressure** are not modeled as
  first-class effects; they are folded into the fitted per-stage coefficients.
- **Overhead** is a single median residual (≈ 0); no per-batch overhead model.
- **R** is a diagnostic decomposition and is only reliable on non-tiny,
  reader-dominant slices; tiny slices (edges < 512) are flagged, not trusted.
- **D_span** accuracy (≈ 4–13% depending on group) bounds the E2E serial
  accuracy; improving E2E means improving the D-stage model.
- The E2E prediction set is restricted to real one-partition L0 slices, where
  the B model is in its calibrated domain. Multi-partition / carry / arbitrary
  new graphs are out of scope for this first version.

## 11. Follow-up work to tighten the model

1. **Reader microbenchmark sweep** decoupling edge streaming from vertex-word
   sweep/scatter, to replace the folded reader coefficients with a
   structure-resolved reader model (and fix the tiny-case behaviour).
2. **B_pred for non-L0 / multi-partition E2E** — extend the E2E predictions
   beyond one-partition slices once B evidence covers those maintenance modes.
3. **Overlap evidence** — dedicated B/D overlap measurement to test the serial
   assumption and, if warranted, replace `serial_pred` with an overlap-aware
   total.
4. **AXI/stream contention probes** to turn the folded coefficients into
   first-class contention terms.
5. **Per-batch overhead** calibration if multi-batch E2E runs reveal a
   non-constant dispatch/measurement overhead.
