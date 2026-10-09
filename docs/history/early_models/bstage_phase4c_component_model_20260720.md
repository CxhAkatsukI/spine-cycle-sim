# Phase 4C — Current-Hardware B-stage / Maintenance Component Model

_Date: 2026-07-20_

## 1. Goal

Build an analysis-level timing model of the **current** maintenance ("B-stage")
kernel as it already runs on the deployed FPGA, so that we can:

- produce a per-case **component bottleneck breakdown** for the L0-store and
  carry/cascade maintenance paths,
- explain why the previous model over-predicts real one-partition slices, and
- estimate a small number of **what-if** speedups without touching hardware.

This is strictly a *simulator-side* modelling exercise over existing evidence.

## 2. Scope — no HLS / no xclbin changes

- **The HLS kernel was not modified.**
- **The xclbin was not rebuilt.** All numbers come from previously captured host
  stdout under `results/…`.
- Reference hardware for the evidence:
  `/data/feiyang/spine-dynamic-graph-builds/stream_sparse_carry_cursors_local_20260716_160954/compact_validation_20260717/hw_134_routed_accepted/xclbin/spine_partitioned_split_e2e.hw.xclbin`
  (134 MHz; `maint_ms → cycles = maint_ms * 134 * 1000`).
- Reference HLS source (read-only) is
  `spine-dynamic-graph-reduce-levels/src/spine_partitioned.hpp`, branch
  `reduce-levels-for-routing`.

## 3. Evidence directories and reproduction

| Group | Role | Kind | Directory |
|---|---|---|---|
| `phase2b` | calibration | synthetic | `results/phase4c_bstage_phase2b_current_hw_20260720_111449` |
| `phase4c_onepart` | calibration | synthetic (1-partition L0) | `results/phase4c_bstage_partition_spread_current_hw_20260720_114845` |
| `phase2d_holdout` | holdout | synthetic | `results/phase4c_bstage_phase2d_holdout_current_hw_20260720_111746` |
| `phase4a_amazon_real` | holdout | real exact slices | `results/phase4a_amazon_exact_slices_hw_20260719_224034` |

Reproduce the analysis (reads the four directories above, fits from the
calibration rows only, validates on the holdout rows):

```bash
cd /home/chuxiao/spine-cycle-sim
OUT=results/phase4c_bstage_component_model_$(date +%Y%m%d_%H%M%S)
python3 scripts/analyze_bstage_component_model.py --out-dir "$OUT"
```

Tests:

```bash
python3 -m unittest tests.test_hw_calibration
python3 -m unittest tests.test_bstage_component_model
python3 -m unittest discover -s tests
```

The raw HW evidence itself can be regenerated with
`scripts/run_hw_maintenance_calibration.py --matrix {phase2b,phase2d_holdout,phase4c_partition_spread}`
against the xclbin above (this *does* require the FPGA; the analysis does not).

## 4. Model structure

### 4.1 L0 store path

The previous structural model treated every L0 store as a 16-partition star and
therefore over-charged real one-partition slices by ~13×. The current-HW model
instead fits four terms directly from the calibration L0 evidence
(`phase2b` 16-partition star + `phase4c_onepart` one-partition):

```
cycles = fixed
       + active_parts               * c_part
       + edges                      * c_edge
       + edges * active_parts       * c_edge_part
```

Fitted coefficients (ordinary least squares over 12 calibration L0 cases):

| term | value | meaning |
|---|---|---|
| `fixed` | 35132.7 | kernel dispatch / metadata fixed cost |
| `c_part` | 1682.9 | per active-partition setup (epoch / page metadata) |
| `c_edge` | 38.34 | common per-edge scan work (hot/cold + 16-family pre-count), independent of partition count |
| `c_edge_part` | 221.09 | **composite** per active-partition, per-edge cost of the active-partition filter scan **and** the coalesced level write |

`c_edge_part` is explicitly a **composite**: with the current evidence the
active-partition filter scan and the level write cannot be separated (they share
the same per-partition pass over `num_edges`). We do **not** claim an exact
split.

### 4.2 Carry / cascade path

The carry path reuses the existing structural counters and calibration constants
from `spine_cycle_sim/calibration/maintenance.py`:

- scan iteration cycles: **145**
- payload / output-edge cycles: **80**
- row-cursor cycles: **130**
- refill-stall cycles: **1**

and adds a single positive **fixed residual correction** fitted from the
`phase2b` carry residuals:

```
cycles = structural_estimate + fixed_residual      (fixed_residual = 53426, positive median)
```

## 5. How each path maps to HLS actions

Line references are into `spine_partitioned.hpp` (`reduce-levels-for-routing`).

### L0 store (`partitioned_run_maintenance` → `partitioned_write_l0_all_partitions`, ~L6021/L4824)

| component | HLS action |
|---|---|
| `fixed_dispatch` | kernel dispatch, `partitioned_meta_control_valid`, counter write-back (~L5932) |
| `hot_cold_input_scan` | the single `PARTITIONED_MAINT_COUNT_HOT_COLD_INPUT` pass over `num_edges` (~L5987) |
| `family_precount_scan` | 16× `partitioned_count_l0_coalesced_rows_family` (~L3339, invoked per family at ~L4862) — the repeated per-family pre-count scan |
| `active_partition_filter_and_level_write` | per **active** partition, `partitioned_write_l0_partition` (~L4808) re-scans all `num_edges` to filter its family and writes coalesced rows/pages in the same pass. Empty partitions early-exit (`edges==0`), so cost scales with `edges × active_parts` |
| `page_epoch_or_metadata_update` | epoch stamping / page metadata (`partitioned_slice_epoch_read_family`, new epoch, `l0_pages_epoch_stamped`, ~L4656), scaling with active partitions |
| `overflow_or_fallback_diagnostic` | overflow / full-clear fallback path (not exercised by the current evidence → modelled as 0) |

The `edges × c_edge` term is apportioned **1:16** into `hot_cold_input_scan` and
`family_precount_scan` because the shared scan is one hot/cold pass plus 16
family pre-count passes. **This 1:16 split is an explanatory apportionment of a
single fitted coefficient, not an independent hardware counter.**

### Carry / cascade (`partitioned_write_carry_target_all_partitions`, ~L5394/L6033)

| component | HLS action |
|---|---|
| `fixed_dispatch` | fitted fixed residual (dispatch/metadata not captured structurally) |
| `hot_cold_input_scan` / `family_precount_scan` | new-batch scan + per-family filter (`partitioned_new_batch_next_for_family`, ~L3889); 1:16 apportionment of the scan budget |
| `cursor_row_walk` | carry cursor row advancement (`rows_entered × 130`) |
| `payload_merge_and_level_write` | old+new payload merge and level write in `partitioned_write_carry_target_family` (~L4329), `(old_edges + output_edges) × 80` |
| `refill_stall` | cursor refill stalls (`refill_stalls × 1`) |
| `page_epoch_or_metadata_update` | page-id write-back + per-level metadata commit (derived by difference so components sum exactly to the structural estimate) |
| `overflow_or_fallback_diagnostic` | commit-failure / overflow path (not exercised → 0) |

## 6. Output files

`scripts/analyze_bstage_component_model.py --out-dir <DIR>` writes:

- **`component_model.json`** — fitted coefficients, carry constants + residual,
  the 1:16 scan-split note, trust thresholds, calibration error metrics, and the
  evidence manifest.
- **`component_predictions.csv`** — one row per case with `group, role, case,
  mode, target_level, batch_edges, active_partitions, pages_epoch_stamped,
  actual_cycles, predicted_cycles, error_pct, abs_error_pct, trusted_status,
  evidence_note, top_component, top_component_cycles`, then per-component
  `cycles`/`share`, then per-what-if `cycles`/`speedup`.
- **`group_summary.csv`** — per `(role, group, mode)` case counts, median/max
  absolute error, and trusted/borderline/untrusted tallies.

Trust classification (on `abs_error_pct`): `≤15%` trusted, `≤30%` borderline,
`>30%` untrusted. Cases with `edges < 512` or `maint_ms_jitter_pct > 5%` are
flagged in `evidence_note` (fixed-cost/timer-noise dominated).

## 7. Results (`group_summary`)

| role | group | mode | cases | median abs err % | max abs err % | trusted | borderline |
|---|---|---|---|---|---|---|---|
| calibration | phase2b | carry | 13 | 0.23 | 2.21 | 13 | 0 |
| calibration | phase2b | l0_store | 6 | 0.04 | 1.57 | 6 | 0 |
| calibration | phase4c_onepart | l0_store | 6 | 0.50 | 22.15 | 5 | 1 |
| holdout | phase2d_holdout | carry | 11 | 0.20 | 1.24 | 11 | 0 |
| holdout | phase2d_holdout | l0_store | 5 | 0.02 | 0.09 | 5 | 0 |
| holdout | phase4a_amazon_real | l0_store | 12 | 0.54 | 27.84 | 10 | 2 |

The only borderline/high-error cases are the tiny, high-jitter ones
(`phase4c_l0_onepart_e10`, `amazon_top1_exact` at 10 edges, `amazon_top8_exact`
at 80 edges) — all flagged via `evidence_note`. Every non-tiny holdout case,
including the real exact Amazon slices, is **trusted (<2%)**.

Headline validation: the one-partition L0 model predicts the real
`amazon_top4096`/`stride4096`/`top512` slices to within ~0.2–0.7%, whereas
treating them as a 16-partition star (the old behaviour) over-predicts by
**~1200–1280%**.

## 8. Typical bottleneck conclusions

- **L0 store (both 16-partition star and one-partition real slices):** the
  dominant component is `active_partition_filter_and_level_write`. Because each
  active partition re-scans all edges, a 16-partition star spends ~13× the
  per-input-edge cost of a one-partition slice. Real Amazon slices are
  one-partition (`l0_partitions_written=1`), so they land on the cheap branch.
- **Carry, shallow / wide batches (e.g. L1, large `edges`):** the dominant
  component is the repeated `family_precount_scan` (16 per-family passes).
- **Carry, deep targets (e.g. L4):** the dominant component shifts to
  `payload_merge_and_level_write` as the merged old+new payload grows.

## 9. What-if conclusions

Two what-ifs are always emitted; a third (L0-only) is emitted for star cases.

1. **`halve_repeated_filter_scans`** — halve the repeated sorted-edge /
   family-filter scan cost.
   - L0 (filter/write-bound): negligible, ~**1.01–1.07×**.
   - Carry L1 large batch: meaningful, ~**1.75×** (scan-bound).
2. **`halve_level_write_path`** — halve the active-filter + level-write composite
   (L0) or the carry payload-merge + level-write path.
   - L0 star / one-partition / real slices: ~**1.74–1.98×**.
   - Carry deep target (L4): ~**1.33×**.
3. **`l0_single_active_partition`** (L0 only) — collapse a 16-partition star into
   a single active partition.
   - 16-partition star: ~**13.4–13.8×** (this is the modelled cost of the old
     star assumption vs. true one-partition behaviour).
   - One-partition / real slices: **1.0×** (already single-partition).

## 10. Limitations

The following are **not** precisely modelled and are left as fixed/derived or
zeroed terms:

- **AXI outstanding transactions** and DRAM latency hiding — folded into the
  fitted per-edge coefficients, not resolved independently.
- **Stream backpressure** between kernel stages — not represented.
- **Page coefficient** — the per-page/metadata term is fitted/derived, not
  measured against a dedicated page-count sweep.
- **Overflow / fallback / full-clear** paths — `overflow_or_fallback_diagnostic`
  is 0 because no evidence case exercises it.
- The **L0 filter vs. level-write split** is a composite by construction (shared
  per-partition pass); the 1:16 scan apportionment is explanatory only.
- Very small batches (`edges < 512`) are fixed-cost/timer-noise dominated and
  are flagged, not trusted.

## 11. Follow-up microbenchmarks to reduce error further

To split the composites and pin the currently-folded effects, the next evidence
sweeps would be:

1. **Page-count sweep at fixed edges** — vary `l0_pages_epoch_stamped` /
   `cold_page_ids_written` independently of `edges` to isolate a real page
   coefficient from `c_part`.
2. **Partition-spread sweep (2, 4, 8 active partitions)** — currently we only
   have 1 and 16; intermediate points would confirm strict linearity of
   `edges × active_parts` and tighten `c_edge_part`.
3. **Filter-only vs. write-only variants** — a build/counter that separates the
   family-filter scan from the coalesced write would let us split the
   `active_partition_filter_and_level_write` composite instead of apportioning.
4. **Overflow / full-clear fallback cases** — to calibrate
   `overflow_or_fallback_diagnostic` instead of zeroing it.
5. **Deep-target payload sweep** — larger `old_edges` at fixed scan to firm up
   the carry `payload_merge_and_level_write` coefficient.
