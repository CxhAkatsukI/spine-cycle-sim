# Phase 3A.2 D-stage Tile-level Model

Date: 2026-07-19

## Goal

Implement and validate a tile-level D-stage schedule/timing model to fix the
fast/full mixed-path gap exposed by `tiny_mixed_fallback`.

Scope:

- D-stage tile-level timing only.
- No AXI cycle-accurate model.
- No real-graph generalization claim.
- No kernel/HLS logic change.
- Host-side workload/instrumentation changes are allowed.
- Keep aggregate model and tile-level model side by side.

## Code Changes

Simulator repo changes:

- `spine_cycle_sim/models/dstage.py`
  - New host-reference-style tile schedule builder.
  - Produces one `TileScheduleEntry` per touched tile.
- `spine_cycle_sim/models/spine.py`
  - Exposes `dstage_tile_*` counters and `dstage_tile_schedule` in simulator results.
  - Keeps existing aggregate counters.
- `spine_cycle_sim/workloads/generators.py`
  - Adds `generate_tile_workload()`, matching the HLS host `--tile-work` generator.
- `scripts/run_hw_dstage_readiness.py`
  - Adds `phase3a2_tile_calibration`, `phase3a2_tile_holdout`, and
    `phase3a2_tile_regression` matrices.
  - Parses `PARTITIONED_CSR_E2E_TILE_SCHEDULE` into `tile_schedule.csv`.
- `scripts/compare_dstage_tile_schedule.py`
  - Compares HW-emitted tile schedules with simulator schedules.
- `scripts/analyze_hw_dstage_tile_timing.py`
  - Fits and validates `tile_schedule_v1` timing from `summary.csv` and
    `tile_schedule.csv`.
- Tests:
  - `tests/test_dstage_tile_schedule.py`
  - `tests/test_hw_dstage_readiness.py`

HLS host-only prerequisite:

- Repo: `/home/chuxiao/spine-dynamic-graph-reduce-levels`
- Branch: `codex/phase3a-dstage-readiness`
- Host doc: `/home/chuxiao/spine-dynamic-graph-reduce-levels/docs/phase3a2_tile_schedule_host_20260719.md`

## Artifacts

Hardware xclbin:

```text
/data/feiyang/spine-dynamic-graph-builds/stream_sparse_carry_cursors_local_20260716_160954/compact_validation_20260717/hw_134_routed_accepted/xclbin/spine_partitioned_split_e2e.hw.xclbin
sha256=57f1459e53145f63e89845d7a694e52db548f90611d9d8cd665a413f67bf12a0
```

Instrumented host:

```text
/home/chuxiao/spine-dynamic-graph-reduce-levels/tests/test_integration/host_partitioned_csr_e2e_smoke
sha256=05169554b92f591a5e5d68850d0e2dbc04fac98e0e85af2972107b634249fba2
```

Output directories:

- Calibration HW: `results/dstage_phase3a2_tile_calibration_hw_20260719_113229`
- Holdout HW: `results/dstage_phase3a2_tile_holdout_hw_20260719_113452`
- Regression HW: `results/dstage_phase3a2_tile_regression_hw_20260719_113725`
- Tile timing analysis: `results/dstage_phase3a2_tile_analysis_20260719_113628`
- Aggregate-on-tile analysis: `results/dstage_phase3a2_aggregate_on_tile_analysis_20260719_113648`
- Tiny-mixed regression analysis: `results/dstage_phase3a2_tile_regression_analysis_20260719_113735`

## Reproduction Commands

Run calibration:

```bash
cd /home/chuxiao/spine-cycle-sim
OUT=results/dstage_phase3a2_tile_calibration_hw_$(date +%Y%m%d_%H%M%S)
printf "%s\n" "$OUT" > /tmp/spine_phase3a2_tile_calibration_outdir.txt
python3 scripts/run_hw_dstage_readiness.py \
  --matrix phase3a2_tile_calibration \
  --out-dir "$OUT" \
  --repeats 3 \
  --timeout 300
```

Check calibration schedule alignment:

```bash
CAL=$(cat /tmp/spine_phase3a2_tile_calibration_outdir.txt)
python3 scripts/compare_dstage_tile_schedule.py \
  --hw-dir "$CAL" \
  --out-dir "$CAL/schedule_compare"
```

Run holdout:

```bash
OUT=results/dstage_phase3a2_tile_holdout_hw_$(date +%Y%m%d_%H%M%S)
printf "%s\n" "$OUT" > /tmp/spine_phase3a2_tile_holdout_outdir.txt
python3 scripts/run_hw_dstage_readiness.py \
  --matrix phase3a2_tile_holdout \
  --out-dir "$OUT" \
  --repeats 3 \
  --timeout 300
```

Check holdout schedule alignment:

```bash
HOLD=$(cat /tmp/spine_phase3a2_tile_holdout_outdir.txt)
python3 scripts/compare_dstage_tile_schedule.py \
  --hw-dir "$HOLD" \
  --out-dir "$HOLD/schedule_compare"
```

Fit and validate tile-level timing:

```bash
CAL=$(cat /tmp/spine_phase3a2_tile_calibration_outdir.txt)
HOLD=$(cat /tmp/spine_phase3a2_tile_holdout_outdir.txt)
OUT=results/dstage_phase3a2_tile_analysis_$(date +%Y%m%d_%H%M%S)
printf "%s\n" "$OUT" > /tmp/spine_phase3a2_tile_analysis_outdir.txt
python3 scripts/analyze_hw_dstage_tile_timing.py \
  --calibration-dir "$CAL" \
  --holdout-dir "$HOLD" \
  --out-dir "$OUT" \
  --freq-mhz 134
```

Run original `tiny_mixed_fallback` regression:

```bash
OUT=results/dstage_phase3a2_tile_regression_hw_$(date +%Y%m%d_%H%M%S)
printf "%s\n" "$OUT" > /tmp/spine_phase3a2_tile_regression_outdir.txt
python3 scripts/run_hw_dstage_readiness.py \
  --matrix phase3a2_tile_regression \
  --out-dir "$OUT" \
  --repeats 3 \
  --timeout 300
```

## Calibration Matrix

All 36 calibration HW runs passed.

| Case | Repeats | conv_span_ms | fast tiles | full tiles | gathered words | swept words |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| `tile_calib_fast_128` | 3/3 | 0.239808 | 1 | 0 | 128 | 0 |
| `tile_calib_fast_1024` | 3/3 | 0.471854 | 1 | 0 | 1024 | 0 |
| `tile_calib_fast_4095` | 3/3 | 1.264020 | 1 | 0 | 4095 | 0 |
| `tile_calib_fast_4096` | 3/3 | 1.316000 | 1 | 0 | 4096 | 0 |
| `tile_calib_full_4097` | 3/3 | 2.259210 | 0 | 1 | 0 | 8196 |
| `tile_calib_full_4098` | 3/3 | 2.229310 | 0 | 1 | 0 | 8198 |
| `tile_calib_full_8192` | 3/3 | 3.143490 | 0 | 1 | 0 | 16386 |
| `tile_calib_full_32768` | 3/3 | 8.602980 | 0 | 1 | 0 | 65538 |
| `tile_calib_mixed_4096_4097` | 3/3 | 3.263270 | 1 | 1 | 4096 | 8196 |
| `tile_calib_mixed_128_8192` | 3/3 | 3.228180 | 1 | 1 | 128 | 16386 |
| `tile_calib_mixed_1024_16384` | 3/3 | 5.208170 | 1 | 1 | 1024 | 32770 |
| `tile_calib_mixed_128_32768` | 3/3 | 8.586720 | 1 | 1 | 128 | 65538 |

Schedule alignment:

- Calibration tile entries: 48
- Failures: 0
- Status: PASS

Tile-level calibration fit:

- Samples: 12
- Median absolute error: 0.521%
- Max absolute error: 2.018%
- Within 20%: 12/12

## Holdout Result

All 24 holdout HW runs passed.

Schedule alignment:

- Holdout tile entries: 36
- Failures: 0
- Status: PASS

Tile-level holdout timing:

- Samples: 8
- Median absolute error: 0.376%
- Max absolute error: 5.609%
- Within 10%: 8/8
- Within 20%: 8/8
- Outliers above 20%: none

| Case | Actual ms | Predicted ms | Error |
| --- | ---: | ---: | ---: |
| `tile_holdout_fast_256` | 0.270248 | 0.271309 | 0.39% |
| `tile_holdout_fast_2048` | 0.760353 | 0.746601 | -1.81% |
| `tile_holdout_full_16384` | 4.959790 | 4.961896 | 0.04% |
| `tile_holdout_full_49152` | 12.144800 | 12.188411 | 0.36% |
| `tile_holdout_mixed_256_16384` | 5.049140 | 5.031223 | -0.35% |
| `tile_holdout_mixed_2048_49152` | 12.703600 | 12.696079 | -0.06% |
| `tile_holdout_mixed_4095_8192` | 4.125580 | 4.163652 | 0.92% |
| `tile_holdout_mixed_4098_32768` | 17.269900 | 16.301181 | -5.61% |

## Aggregate vs Tile-level

The old aggregate feature model was also fitted on the same tile calibration
matrix and evaluated on the same tile holdout matrix.

Aggregate-on-tile holdout:

- Median absolute error: 1.049%
- Max absolute error: 40.011%
- Within 20%: 7/8
- Outlier: `tile_holdout_mixed_4098_32768`

Tile-level holdout:

- Median absolute error: 0.376%
- Max absolute error: 5.609%
- Within 20%: 8/8
- Outliers: none

Conclusion: aggregate features are good on many clean cases, but still fail on
one mixed/full-range composition. The tile-level model fixes that structural
gap by preserving per-tile work and path composition.

## Tiny Mixed Regression

The original diagnostic case was rerun as:

```bash
--tiny-mixed-fallback --print-tile-schedule
```

Results:

- HW runs: 3/3 PASS
- Schedule entries: 6
- Schedule compare failures: 0
- Tile-level timing error: 1.584%
- Within 20%: yes

This directly fixes the earlier `tiny_mixed_fallback` gap.

## What We Can Claim

Supported:

- Simulator and host reference agree on tile schedule for the Phase 3A.2
  boundary/range/mixed matrices.
- Tile-level timing predicts D-stage `conv_span_ms` accurately for the tested
  synthetic tile regimes.
- The original `tiny_mixed_fallback` diagnostic is now within 20%.
- Tile-level modeling gives a stronger mixed-path result than aggregate
  counters on this test set.

Not yet supported:

- Real graph generalization.
- Hot/cold tile scheduling.
- AXI outstanding/burst/FIFO cycle accuracy.
- Full end-to-end timing replacement for every workload class.
- Claiming individual regression coefficients are causal hardware costs.

## Validation

Simulator tests:

```bash
cd /home/chuxiao/spine-cycle-sim
python3 -m py_compile scripts/run_hw_dstage_readiness.py scripts/compare_dstage_tile_schedule.py scripts/analyze_hw_dstage_tile_timing.py spine_cycle_sim/models/dstage.py spine_cycle_sim/models/spine.py spine_cycle_sim/workloads/generators.py tests/test_dstage_tile_schedule.py tests/test_hw_dstage_readiness.py
python3 -m unittest discover -s tests -v
```

Result:

```text
Ran 26 tests
OK
```

HLS host:

```bash
cd /home/chuxiao/spine-dynamic-graph-reduce-levels/tests/test_integration
make host_partitioned_csr_e2e_smoke
```

Result:

```text
make: 'host_partitioned_csr_e2e_smoke' is up to date.
```

## Next

The next useful step is to apply the tile-level backend to a small set of
real-graph-derived or host-generated non-tile-work workloads, but only after
adding schedule support for those workload shapes. Otherwise we would again be
comparing timing with an unverified schedule.

