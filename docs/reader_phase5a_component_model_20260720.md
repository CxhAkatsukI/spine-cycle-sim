# Phase 5A — Reader / Readmaintenance Structured Component Model

_Date: 2026-07-20_

## 1. Goal

The E2E phase found that real one-partition Amazon exact slices are
**reader-dominant**: 11/12 have `median_reader_ms ≈ median_conv_span_ms`
(e.g. `top4096`: reader ≈ 437.86 ms, conv_span ≈ 438.30 ms). Phase 5A opens up
that reader time with a **structured, non-negative component model** so the
reader bottleneck is explained by physically meaningful terms, calibrated on
synthetic microbench-style evidence and validated on real slices, and feeds a
downstream E2E report.

## 2. Scope and boundaries

- **No HLS kernel changes, no xclbin rebuild.**
- The reader microbench reuses the existing D-stage readiness host workload
  vocabulary — a new **matrix selector** (`phase5a_reader_calibration` /
  `phase5a_reader_holdout`) was added to `scripts/run_hw_dstage_readiness.py`; no
  host source change was required.
- Long HW runs are executed by Chuxiao. This phase generates the commands,
  dry-runs them, and builds the calibration/validation/analysis pipeline over
  existing evidence.
- **`SpineV0Simulator.run()` default behaviour is unchanged.**
- **R is a diagnostic sub-model of the D span and is NOT added into the serial
  E2E total**, which remains `serial_pred = B_pred + D_span_pred + overhead_model`
  (`D_tail = max(0, D_span - R)`).

## 3. Model structure

Non-negative least squares (coordinate descent with a per-coefficient
non-negativity clamp), so no component is "explained" by a negative coefficient:

```
R_cycles = fixed
         + c_edge_stream  * traversed_edges
         + c_replay       * active_records_x_touched_tiles
         + c_fast         * fast_gather_scatter_words
         + c_full         * full_swept_words
         + c_fallback     * fallback_penalty        (fallback_count * clipped_ranges)
         + c_partition    * partition_spread        (distinct partitions touched)
```

Fitted coefficients (synthetic calibration, relative weighting):

Fitted coefficients (synthetic calibration **incl. the Phase 5A orthogonal
microbench**, relative weighting):

| component | coefficient | meaning |
|---|---|---|
| `fixed` | ~18.8k | reader event/window fixed cost |
| `edge_stream` | ~4.2 /edge | streaming traversed edges from HBM |
| `active_record_replay` | ~1093 /(record·tile) | active source records replayed across touched tiles |
| `fast_gather_scatter` | ~0 /word | fast-path gather/scatter vertex words (weakly identified) |
| `full_sweep` | ~1.0 /word | normal full-tile swept vertex words |
| `fallback_sweep` | 0.0 | fallback full-vertex sweep words — penalty is **real but not yet separable** (see §9) |
| `partition_spread` | 0.0 | HBM-bank spread — **measured negligible** by the orthogonal sweep (§9) |

The Phase 5A microbench was run on hardware (2× Alveo U55C, cal 14/14 and
holdout 9/9 fully passed). Its two zero coefficients are now backed by
measurement rather than by an identifiability gap — see §9 for what the
orthogonal contrasts revealed (partition spread is genuinely flat; the fallback
penalty is real at ~4.24 cycles/word but is masked in the full fit by
`active_record_replay` over-prediction in the striped regime — the newly
identified next lever is reader **replay non-linearity**, not a missing fallback
feature).

### Measurement-window limitation

`median_reader_ms` is the readmaintenance / CONV compute-unit **event duration**
in the full smoke run, not a pure hardware reader-only cycle count. Small
synthetic cases are dominated by fixed overhead and timer noise and therefore
carry high *relative* error. The model is fit with relative weighting so the
(much larger) reader-dominant cases — where the reader signal is real — drive
the coefficients.

## 4. Mapping to the reader / readmaintenance hardware action

The simulator's `ReadMaintenance` (`spine_cycle_sim/models/spine.py`, ~L948)
does three things, which the component model mirrors:

1. **wait for storage/memory idle** → part of `fixed`.
2. **scan metadata** at `vertices / readmaintenance_vertex_scan_rate` → `fixed` +
   the constant part of the reader window.
3. **issue per-family HBM read requests** to bank `family_index % num_partitions`
   → the volume terms: `edge_stream` (edges read), `active_record_replay`
   (records replayed across touched tiles — the dominant term for real slices),
   `fast_gather_scatter` / `full_sweep` (vertex-word movement), and
   `partition_spread` (HBM-bank spread).

## 5. Pre-declared calibration / holdout split

The split is fixed in `scripts/analyze_reader_component_model.py` **before**
fitting (not chosen after seeing results):

- **Calibration (synthetic):** `dstage_phase3a4_replay_calibration`,
  `phase3c_full_partition_calibration`, `phase3b_bottleneck_synthetic`.
- **Holdout (synthetic):** `phase3c_full_partition_holdout`,
  `dstage_phase3a4_replay_holdout`, `phase3c_final_validation`.
- **Holdout (real / real-like):** `phase4a_amazon_exact_slices` (primary),
  `phase3d_amazon_slices`.

## 6. Phase 5A reader microbench matrix

`phase5a_reader_calibration` (14 cases) and `phase5a_reader_holdout` (9 cases)
cover the six required axes, pre-split before any HW run:

| axis | calibration | holdout |
|---|---|---|
| edge_stream | e512, e4096, e32768 | e1024, e8192, e65536 |
| replay | s16×t1, s64×t4 | s32×t2, s128×t8 |
| full_sweep | w8192, w32768 | (mixed) |
| fast_path | w2048 | (mixed) |
| fallback | boundary_low, boundary_high | boundary_high (8193) |
| partition_spread | 8 tiles over 1/2/4/8 partitions | 4 tiles over 1 / 4 partitions |
| mixed fast/full | — | fast+full pair |

**Orthogonality note (partition_spread).** The partition-spread sweep holds the
tile count / per-tile work / replay **constant** (8 tiles at work 64) and varies
*only* how many distinct partitions (HBM banks) those tiles land on. This is
deliberate: a per-partition-fixed sweep (e.g. 1p/4p/16p each at work 64) makes
`partition_count` collinear with the total edge/replay volume, so NNLS would
again absorb it into `active_record_replay` and report a zero coefficient — as
happened with the existing evidence. The `fallback` pair
(`boundary_low`=4096 → no fallback vs `boundary_high`=4097 → fallback) is the
analogous matched contrast: everything else is held near-constant so the
reader_ms difference isolates the fallback penalty. Note that
`partition_spread` may legitimately turn out ≈0 or beneficial (more banks →
more parallelism), which the non-negative fit clamps to 0; the matched contrast
lets us see that directly.

Generate and dry-run (Chuxiao runs the actual HW):

```bash
python3 scripts/run_hw_dstage_readiness.py --matrix phase5a_reader_calibration \
    --out-dir results/phase5a_reader_calibration_$(date +%Y%m%d_%H%M%S) --dry-run
python3 scripts/run_hw_dstage_readiness.py --matrix phase5a_reader_holdout \
    --out-dir results/phase5a_reader_holdout_$(date +%Y%m%d_%H%M%S) --dry-run
```

Once the HW runs exist, re-run the analysis pointing `--calibration-dir` at the
new microbench directories to isolate the `fallback` and `partition_spread`
coefficients.

## 7. Reproduction

```bash
cd /home/chuxiao/spine-cycle-sim
OUT=results/reader_component_model_$(date +%Y%m%d_%H%M%S)
python3 scripts/analyze_reader_component_model.py --out-dir "$OUT"

# Downstream: E2E now uses the reader v2 model for R (still diagnostic).
python3 scripts/analyze_e2e_component_model.py --out-dir results/e2e_$(date +%Y%m%d_%H%M%S)

python3 -m unittest tests.test_reader_component_model
python3 -m unittest discover -s tests
```

## 8. Output files

`scripts/analyze_reader_component_model.py --out-dir <DIR>`:

- **`reader_model.json`** — coefficients, form, measurement-window note, the
  `not_separately_identifiable` list, trust thresholds, evidence manifest.
- **`reader_predictions.csv`** — per case: `group, role, case, sweep, path_class,
  traversed_edges, active_records, touched_tiles, partition_count,
  fallback_count`, reader actual/pred/error, `trusted_status`, `evidence_note`,
  `top_component`, `conv_span_actual_cycles`, `kernel_e2e_actual_cycles`,
  `reader_share_of_conv_span`, `d_tail_cycles`, per-component cycles/share, and
  per-what-if cycles/speedup.
- **`reader_group_summary.csv`** — per (role, group) median/max abs error,
  trusted/borderline/untrusted tallies, and dominant path class.

`scripts/analyze_e2e_component_model.py` additionally writes
**`e2e_reader_downstream.csv`** (reader v2 component breakdown + reader what-ifs
per E2E case) and records `reader_model_version` / `reader_in_serial_total:false`
in `e2e_model.json`.

## 9. Results

`reader_group_summary` (abs error %):

| role | group | cases | median | max | dominant path |
|---|---|---|---|---|---|
| holdout_real | phase4a_amazon_exact | 12 | **7.86** | 17.31 | fast_only |
| holdout_real | phase3d_amazon (real-like) | 15 | 22.80 | 81.86 | fast_only |
| calibration | phase3a4_replay | 31 | 21.67 | 74.23 | fast_only |
| calibration | phase3b_bottleneck | 22 | 23.14 | 85.45 | fast_only |
| calibration | phase3c_full_partition | 23 | 39.14 | 110.83 | full_only |
| holdout_synth | phase3c_full_partition_holdout | 12 | 38.86 | 116.27 | fast_only |

The model is calibrated to explain **reader-dominant** behaviour, so it predicts
the real exact slices to **~7.7–7.9% median (11/12 trusted)** (adding the Phase 5A
microbench to calibration leaves this essentially unchanged). Synthetic cases
carry higher relative error because there the reader is a tiny, fixed-overhead-
and timer-noise-dominated fraction of the CONV event window (the
measurement-window limitation), not because the structural coefficients are
wrong.

### 9.1 What the Phase 5A orthogonal microbench measured

The microbench was run on hardware (2× Alveo U55C; cal 14/14, holdout 9/9 fully
passed). Two designed contrasts:

- **partition_spread — genuinely negligible.** Holding 8 tiles / work / replay
  constant and varying only the number of partitions (HBM banks): reader_ms was
  0.558 (1p) / 0.537 (2p) / 0.564 (4p) / 0.522 (8p) ms — flat within ~6% jitter,
  8p marginally *fastest*. So spreading tiles across banks has no measurable
  reader cost (and does not clearly help). The zero coefficient is now a
  measured result, not an identifiability artifact.

- **fallback — a real penalty that the model cannot yet attribute.** Crossing the
  replay-estimate threshold (`striped 4096` → `4097`) flips 16 tiles into a
  full-vertex fallback sweep: reader jumps 433.4 → 499.7 ms (**+66.3 ms /
  8.89M cycles**) for **+2.10M swept words = ~4.24 cycles/word** — about 4× a
  normal full-tile sweep (~1.0/word). The model gained a dedicated
  `fallback_sweep` feature (keyed on fallback swept words, replacing the earlier
  `tile_fallback_count × clipped` proxy), but its coefficient still fits to **0**:
  in the striped fallback cases the linear `active_record_replay` term alone
  (replay 65552 × ~1093 ≈ 71.6M cycles) already *exceeds* the whole measured
  reader (58–67M), leaving no residual for fallback. **The true blocker is reader
  replay non-linearity** — the linear replay term (fit on dense multi-source
  cases) over-predicts the sparse/striped regime by ~23%. Fixing that is the
  prerequisite for isolating the (already-measured, 4.24/word) fallback cost.

## 10. Bottleneck conclusion

For real one-partition Amazon slices the reader bottleneck is
**`active_record_replay`** — active source records replayed across touched tiles,
at ≈ 1090 cycles per (record·tile). In the E2E downstream report it is the top
reader component for 11/12 slices with an 83–99% share (the exception, `top1` at
10 edges, is `fixed`-dominated). Raw edge streaming (`edge_stream`, ≈ 4.8
cyc/edge) and vertex-word movement are secondary.

## 11. Reader what-ifs

Speedups relative to the modeled reader time:

- **`halve_active_record_replay`** ≈ **1.9–2.0×** on real slices — the dominant
  reader lever, because replay is ~85–99% of reader time.
- `halve_full_sweep`, `halve_fast_gather_scatter`, `halve_edge_stream`,
  `remove_fallback_penalty` — all ≈ 1.0× on these slices, since those components
  are small here.

Because reader ≈ conv_span ≈ E2E for these slices, cutting active-record replay
is the most promising reader-side optimization; it is surfaced through
`e2e_reader_downstream.csv` while R stays out of the serial total.

## 12. Limitations

- **`partition_spread` is measured negligible** (flat across 1/2/4/8 partitions),
  so its zero coefficient is now justified, not an artifact.
- **`fallback_sweep` coefficient is still 0** — not for lack of a feature, but
  because `active_record_replay` over-predicts the striped fallback baseline and
  absorbs the budget. The fallback penalty itself is measured (~4.24 cycles/word);
  isolating it in the model requires fixing replay non-linearity first.
- **Reader replay is modeled linearly** (`~1093 /(record·tile)`), which
  over-predicts the sparse/striped regime by ~23%. This is the top open modeling
  gap surfaced by Phase 5A.
- **Measurement window:** `reader_ms` is a CONV CU event duration, not pure
  reader cycles; tiny/synthetic cases are noise-dominated and flagged, not
  trusted.
- Real-like `phase3d_amazon` averaged/aggregate slices validate at ~23% median
  (more structural noise than the exact slices).
- Conclusions apply to the evidence-covered structure and same-class workloads
  (one-partition L0 reader-dominant slices); no claim is made for arbitrary new
  graphs.

## 13. Follow-up

1. **Reader replay non-linearity (top lever).** Model `active_record_replay`
   per-regime (sparse/striped vs dense) or with a saturation term, so the
   striped/high-replay cases stop over-predicting. This is the prerequisite that
   would let `fallback_sweep` pick up its already-measured ~4.24 cycles/word.
2. **Reader-only hardware counter** (vs. the CONV event window) would remove the
   measurement-window noise and let the synthetic cases validate directly.
3. **Path-segmented reader model** (fast_only / full_only / mixed / fallback) if,
   after (1), per-word costs still look path-dependent.
4. Fold the improved coefficients back into the E2E downstream report.
