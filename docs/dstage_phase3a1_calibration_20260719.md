# Phase 3A.1 D-stage HW Timing Calibration

Date: 2026-07-19

## Goal

Calibrate the first D-stage timing model against real `hw` runs.

Primary target:

- `conv_span_ms`, converted to cycles as `median_conv_span_ms * freq_mhz * 1000`.

Diagnostic metrics:

- `conv_ms`
- `reader_ms`

Acceptance criteria:

- Calibration matrix: at least 12 synthetic targeted cases, 3 repeats each.
- Holdout matrix: at least 8 unseen synthetic targeted cases, 3 repeats each.
- No tuning on final holdout.
- Pass if final holdout median absolute error is <= 10% and max absolute error is <= 20%.
- Any outlier above 20% must be explained.

## Hardware And Host Artifacts

The run used the 2026-07-17 accepted routed hardware, because it is the latest available routed `hw` build compatible with the current instrumented host.

| Artifact | Path | SHA256 |
| --- | --- | --- |
| xclbin | `/data/feiyang/spine-dynamic-graph-builds/stream_sparse_carry_cursors_local_20260716_160954/compact_validation_20260717/hw_134_routed_accepted/xclbin/spine_partitioned_split_e2e.hw.xclbin` | `57f1459e53145f63e89845d7a694e52db548f90611d9d8cd665a413f67bf12a0` |
| host executable | `/home/chuxiao/spine-dynamic-graph-reduce-levels/tests/test_integration/host_partitioned_csr_e2e_smoke` | `f62915a0001d40a7b8415449a9b2c87ea6657037b71fab24e1569bbd723908a9` |

Relevant HLS host instrumentation:

- Repo: `/home/chuxiao/spine-dynamic-graph-reduce-levels`
- Branch: `codex/phase3a-dstage-readiness`
- Commit: `c1216f4`
- Instrumentation added `reader_ms` and `conv_span_ms` to the final `PARTITIONED_CSR_E2E_SMOKE` line.

Simulator starting point:

- Repo: `/home/chuxiao/spine-cycle-sim`
- Base commit before this phase: `59a13fe`

## Tooling Changes

Files changed in the simulator repo:

- `scripts/run_hw_dstage_readiness.py`
  - Added `phase3a1_calibration`, `phase3a1_holdout`, and `phase3a1_final_holdout` built-in matrices.
  - Changed the default host executable to the local instrumented host.
  - Records the selected matrix in `matrix.json`.
- `scripts/analyze_hw_dstage_calibration.py`
  - New script to fit a standardized ridge model from HW summary CSVs.
  - Writes `fit.json`, `calibration_predictions.csv`, and optional `holdout_predictions.csv`.
- `tests/test_hw_dstage_readiness.py`
  - Checks that the final holdout matrix is disjoint from calibration and earlier holdout cases.

## Reproduction Commands

Run calibration:

```bash
cd /home/chuxiao/spine-cycle-sim
OUT=results/dstage_phase3a1_calibration_hw_$(date +%Y%m%d_%H%M%S)
printf "%s\n" "$OUT" > /tmp/spine_dstage_phase3a1_calibration_outdir.txt
python3 scripts/run_hw_dstage_readiness.py \
  --matrix phase3a1_calibration \
  --out-dir "$OUT" \
  --repeats 3 \
  --timeout 240
```

Run final holdout:

```bash
cd /home/chuxiao/spine-cycle-sim
OUT=results/dstage_phase3a1_final_holdout_hw_$(date +%Y%m%d_%H%M%S)
printf "%s\n" "$OUT" > /tmp/spine_dstage_phase3a1_final_holdout_outdir.txt
python3 scripts/run_hw_dstage_readiness.py \
  --matrix phase3a1_final_holdout \
  --out-dir "$OUT" \
  --repeats 3 \
  --timeout 300
```

Fit calibration and validate final holdout:

```bash
cd /home/chuxiao/spine-cycle-sim
CAL=$(cat /tmp/spine_dstage_phase3a1_calibration_outdir.txt)
HOLD=$(cat /tmp/spine_dstage_phase3a1_final_holdout_outdir.txt)
OUT=results/dstage_phase3a1_final_analysis_$(date +%Y%m%d_%H%M%S)
printf "%s\n" "$OUT" > /tmp/spine_dstage_phase3a1_final_analysis_dir.txt
python3 scripts/analyze_hw_dstage_calibration.py \
  --calibration-dir "$CAL" \
  --holdout-dir "$HOLD" \
  --out-dir "$OUT" \
  --freq-mhz 134
```

The concrete output directories from this run:

- Calibration: `results/dstage_phase3a1_calibration_hw_20260719_011138`
- Final holdout: `results/dstage_phase3a1_final_holdout_hw_20260719_012257`
- Final analysis: `results/dstage_phase3a1_final_analysis_20260719_012430`

## Calibration Matrix

All 36 calibration runs passed.

| Case | Repeats | conv_span_ms | reader_ms | traversed_edges | active_records | fast_tiles | full_tiles |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| `calib_tiny_default` | 3/3 | 0.358460 | 0.238696 | 7 | 7 | 3 | 0 |
| `calib_sparse_wide` | 3/3 | 0.680929 | 0.296359 | 2 | 1 | 16 | 0 |
| `calib_star_e128` | 3/3 | 1.028390 | 0.775682 | 128 | 16 | 16 | 0 |
| `calib_star_e512` | 3/3 | 1.003710 | 0.887525 | 512 | 16 | 16 | 0 |
| `calib_star_e2048` | 3/3 | 1.285400 | 1.183640 | 2048 | 16 | 16 | 0 |
| `calib_fanout_e1024_s16` | 3/3 | 4.079910 | 3.985350 | 1024 | 256 | 16 | 0 |
| `calib_fanout_e4096_s64` | 3/3 | 15.425700 | 15.225600 | 4096 | 1024 | 16 | 0 |
| `calib_fanout_e8192_s128` | 3/3 | 30.360900 | 30.213200 | 8192 | 2048 | 16 | 0 |
| `calib_repeat_fanout_e256_b2_s32` | 3/3 | 6.993310 | 6.875140 | 512 | 512 | 16 | 0 |
| `calib_repeat_fanout_e512_b3_s64` | 3/3 | 20.211500 | 20.091800 | 1536 | 1536 | 16 | 0 |
| `calib_repeat_star_e1024_b2` | 3/3 | 1.285620 | 1.173640 | 2048 | 16 | 16 | 0 |
| `calib_fallback_forced` | 3/3 | 417.273000 | 416.300000 | 4112 | 4097 | 0 | 16 |

Calibration fit result:

- Samples: 12
- Median absolute error: 0.791%
- Max absolute error: 17.474%
- Within 10%: 11/12
- Within 20%: 12/12

## Timing Model

The fitted target is:

```text
target_cycles = median_conv_span_ms * 134 * 1000
```

The default feature set is intentionally small:

- `median_active_records`
- `median_gathered_vertex_words`
- `median_swept_vertex_words`
- `median_scattered_vertex_words`
- `median_fast_path_tiles`
- `median_full_path_tiles`

The model is standardized ridge regression with:

- `alpha = 1e-6`
- Intercept and coefficients stored in `results/dstage_phase3a1_final_analysis_20260719_012430/fit.json`

Important note: the coefficients should not be interpreted as independent causal costs yet. Several counters are correlated by construction, especially full-tile words and full-tile count. The useful result here is prediction error on unseen workloads, not coefficient meaning.

## Final Holdout Matrix

This matrix was added after fixing the model and was not used for tuning.

All 24 final holdout runs passed.

| Case | Repeats | conv_span_ms | reader_ms | traversed_edges | active_records | fast_tiles | full_tiles |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| `final_star_e384` | 3/3 | 1.076800 | 0.960237 | 384 | 16 | 16 | 0 |
| `final_star_e1536` | 3/3 | 1.182740 | 1.082470 | 1536 | 16 | 16 | 0 |
| `final_star_onepart_e1024` | 3/3 | 0.482664 | 0.180435 | 1024 | 1 | 1 | 0 |
| `final_fanout_e3072_s48` | 3/3 | 11.566100 | 11.479400 | 3072 | 768 | 16 | 0 |
| `final_fanout_e7168_s112` | 3/3 | 26.617600 | 26.487600 | 7168 | 1792 | 16 | 0 |
| `final_repeat_fanout_e384_b3_s48` | 3/3 | 15.231600 | 15.125000 | 1152 | 1152 | 16 | 0 |
| `final_repeat_fanout_e768_b2_s96` | 3/3 | 20.193200 | 20.086000 | 1536 | 1536 | 16 | 0 |
| `final_repeat_star_dense_e768_b2` | 3/3 | 1.149260 | 1.040720 | 1536 | 16 | 16 | 0 |

Final holdout prediction result:

- Samples: 8
- Median absolute error: 0.319%
- Max absolute error: 15.649%
- Within 10%: 7/8
- Within 20%: 8/8
- Outliers above 20%: none

| Case | Actual ms | Predicted ms | Error |
| --- | ---: | ---: | ---: |
| `final_star_e384` | 1.076800 | 0.908291 | -15.65% |
| `final_star_e1536` | 1.182740 | 1.176483 | -0.53% |
| `final_star_onepart_e1024` | 0.482664 | 0.482466 | -0.04% |
| `final_fanout_e3072_s48` | 11.566100 | 11.744736 | 1.54% |
| `final_fanout_e7168_s112` | 26.617600 | 26.602190 | -0.06% |
| `final_repeat_fanout_e384_b3_s48` | 15.231600 | 15.239100 | 0.05% |
| `final_repeat_fanout_e768_b2_s96` | 20.193200 | 20.215212 | 0.11% |
| `final_repeat_star_dense_e768_b2` | 1.149260 | 1.158303 | 0.79% |

The only large final-holdout error is `final_star_e384`, at -15.65%. It is still within the acceptance threshold. This case also had visible run-to-run jitter, so its error should be treated as a small-latency measurement-noise warning, not as a throughput-path failure.

## Diagnostic Mixed-Path Case

An earlier 9-case diagnostic holdout included `holdout_tiny_mixed_fallback`. It is not part of the formal Phase 3A.1 holdout scope, because this phase intentionally targets clean synthetic timing regimes before mixed fast/full-path modeling.

Using the final model on that diagnostic set:

- Directory: `results/dstage_phase3a1_analysis_diagnostic_mixed_20260719_012143`
- Overall diagnostic holdout: median absolute error 5.499%, max absolute error 300.531%
- Outlier: `holdout_tiny_mixed_fallback`
- `holdout_tiny_mixed_fallback`: actual 443046.9 cycles, predicted 1774538.4 cycles, error 300.53%

Conclusion: mixed tiny/full-path behavior is a real future gap and should be handled in Phase 3A.2. It should not be hidden inside the current aggregate metric.

## Current Claims

Supported claims:

- For the targeted synthetic D-stage regimes in Phase 3A.1, the calibrated model estimates `conv_span_ms` within the acceptance target.
- The longer fanout and repeated-fanout cases are especially stable and show low error.
- `reader_ms` is close to `conv_ms` in the longer cases, so the measured D-stage span is dominated by reader/edge traversal behavior for those workloads.

Not yet supported:

- Real graph generalization.
- Hot/cold-specific D-stage timing.
- Mixed tiny/full-path timing.
- AXI-cycle-accurate outstanding request, burst, response FIFO, or stream backpressure behavior.
- Interpreting individual regression coefficients as hardware component costs.
- Claiming full simulator accuracy for end-to-end runtime before this model is integrated into the simulator core.

## Next Step

Integrate this calibrated D-stage model into `spine_cycle_sim/models/spine.py`, then run simulator-vs-HW comparison on the same calibration, final holdout, and a small real-graph external validation set.
