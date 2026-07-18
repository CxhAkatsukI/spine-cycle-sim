# Phase 2D Holdout Validation - 2026-07-18

This note records the first B-stage maintenance holdout validation run for the
Phase 2C calibrated timing model.

## Goal

Phase 2D tests whether the calibrated maintenance timing model generalizes to
unseen synthetic maintenance scenarios.

Important rule:

```text
Do not tune calibrated coefficients using holdout results.
```

The Phase 2C coefficients were kept fixed. This run only measures prediction
error and records pass/fail/outlier behavior.

## Artifacts

Simulator repo:

```text
/home/chuxiao/spine-cycle-sim
base commit 144d005 Calibrate maintenance timing model
```

HW xclbin:

```text
/data/feiyang/spine-dynamic-graph-builds/stream_sparse_carry_cursors_local_20260716_160954/hw_134_attempt1/xclbin/spine_partitioned_split_e2e.hw.xclbin
sha256 4d28a2d2420d4524c7c7fcf48239c027b29fa63d49351ecfcdd8cf0aa37db91d
```

Host executable:

```text
/home/chuxiao/spine-dynamic-graph-reduce-levels/tests/test_integration/host_partitioned_csr_e2e_smoke
sha256 4febd0568e9e910cde1188d058f33e342eb537aef312796d911f5b72cc2c47fb
```

Output directory:

```text
/home/chuxiao/spine-cycle-sim/results/maintenance_phase2d_holdout_hw_20260718_235855
```

Important files:

```text
runs.csv
summary.csv
analysis_phase2d_holdout/summary.csv
analysis_phase2d_holdout/fit.json
raw/<case>/run_N.stdout
raw/<case>/run_N.stderr
raw/<case>/run_N.command.sh
```

## Matrix

The holdout matrix is exposed by:

```bash
python3 scripts/run_hw_maintenance_calibration.py --matrix phase2d_holdout ...
```

It has 16 cases and 3 repeats per case:

```text
16 cases * 3 repeats = 48 HW runs
```

The cases are intentionally different from the 19 Phase 2B calibration points.

### L0 Store Holdout

```text
--star 512
--star 2048
--star 8192
--star 32768
--star 98304
```

### L1 Batch-Edges Holdout

```text
--measure-carry 1 512 64
--measure-carry 1 2048 64
--measure-carry 1 8192 64
--measure-carry 1 32768 64
```

### Target-Level Holdout

```text
--measure-carry 2 8192 64
--measure-carry 3 8192 64
--measure-carry 5 2048 64
--measure-carry 6 1024 64
```

### Source/Page Locality Holdout

```text
--measure-carry 8 256 32
--measure-carry 8 256 128
--measure-carry 8 256 384
```

## Commands

Dry-run:

```bash
cd /home/chuxiao/spine-cycle-sim
python3 scripts/run_hw_maintenance_calibration.py \
  --matrix phase2d_holdout \
  --xclbin /data/feiyang/spine-dynamic-graph-builds/stream_sparse_carry_cursors_local_20260716_160954/hw_134_attempt1/xclbin/spine_partitioned_split_e2e.hw.xclbin \
  --out-dir results/maintenance_phase2d_holdout_hw_20260718_235855 \
  --dry-run
```

HW run:

```bash
cd /home/chuxiao/spine-cycle-sim
python3 scripts/run_hw_maintenance_calibration.py \
  --matrix phase2d_holdout \
  --xclbin /data/feiyang/spine-dynamic-graph-builds/stream_sparse_carry_cursors_local_20260716_160954/hw_134_attempt1/xclbin/spine_partitioned_split_e2e.hw.xclbin \
  --out-dir results/maintenance_phase2d_holdout_hw_20260718_235855 \
  --repeats 3 \
  --timeout 300 \
  --freq-mhz 134 \
  --allow-failures
```

Analysis:

```bash
cd /home/chuxiao/spine-cycle-sim
python3 scripts/analyze_hw_maintenance_calibration.py \
  --input-dir results/maintenance_phase2d_holdout_hw_20260718_235855 \
  --out-dir results/maintenance_phase2d_holdout_hw_20260718_235855/analysis_phase2d_holdout \
  --freq-mhz 134
```

## Run Status

All 48 HW runs completed with `PASS`.

The largest repeat jitter was about 1.33%, and most points were far below 1%.
The median values are stable enough for holdout validation.

## Error Summary

Prediction uses the fixed Phase 2C model:

```text
predicted_cycles = sim_maintenance_estimated_cycles
hw_cycles = median_maint_ms * 134000
```

Overall:

```text
holdout cases: 16
within 10%: 16 / 16
within 15%: 16 / 16
median absolute error: 0.20%
max absolute error: 4.82%
```

By sweep:

| sweep | cases | median abs error | max abs error |
| --- | ---: | ---: | ---: |
| `holdout_l0_store` | 5 | 0.21% | 2.75% |
| `holdout_l1_batch_edges` | 4 | 0.73% | 4.82% |
| `holdout_source_count` | 3 | 0.10% | 0.88% |
| `holdout_target_level` | 4 | 0.17% | 0.39% |

Worst case:

```text
holdout_carry_l1_batch_e512_s64
HW cycles: 1,462,101
predicted cycles: 1,391,696
error: -4.82%
```

## Per-Case Results

| case | sweep | HW cycles | predicted cycles | error |
| --- | --- | ---: | ---: | ---: |
| `holdout_l0_store_e512` | L0 store | 1,882,231 | 1,830,448 | -2.75% |
| `holdout_l0_store_e2048` | L0 store | 7,381,966 | 7,321,648 | -0.82% |
| `holdout_l0_store_e8192` | L0 store | 29,347,608 | 29,286,448 | -0.21% |
| `holdout_l0_store_e32768` | L0 store | 117,200,286 | 117,145,648 | -0.05% |
| `holdout_l0_store_e98304` | L0 store | 351,464,580 | 351,436,848 | -0.01% |
| `holdout_carry_l1_batch_e512_s64` | L1 batch | 1,462,101 | 1,391,696 | -4.82% |
| `holdout_carry_l1_batch_e2048_s64` | L1 batch | 5,614,185 | 5,546,576 | -1.20% |
| `holdout_carry_l1_batch_e8192_s64` | L1 batch | 22,224,838 | 22,166,096 | -0.26% |
| `holdout_carry_l1_batch_e32768_s64` | L1 batch | 88,629,208 | 88,644,176 | 0.02% |
| `holdout_carry_target_l2_e8192_s64` | target level | 24,832,746 | 24,796,000 | -0.15% |
| `holdout_carry_target_l3_e8192_s64` | target level | 30,047,892 | 30,051,504 | 0.01% |
| `holdout_carry_target_l5_e2048_s64` | target level | 15,486,514 | 15,456,592 | -0.19% |
| `holdout_carry_target_l6_e1024_s64` | target level | 13,136,060 | 13,085,216 | -0.39% |
| `holdout_carry_source_t8_e256_s32` | source locality | 11,401,109 | 11,395,264 | -0.05% |
| `holdout_carry_source_t8_e256_s128` | source locality | 11,650,228 | 11,661,504 | 0.10% |
| `holdout_carry_source_t8_e256_s384` | source locality | 11,765,615 | 11,661,504 | -0.88% |

## Conclusion

The Phase 2C B-stage calibrated timing model passed the Phase 2D holdout
validation.

Safe claim after Phase 2D:

```text
The B-stage maintenance timing model is not only fitted to the original 19
calibration points. It also predicts 16 unseen synthetic maintenance holdout
cases within 10% error, with median absolute error around 0.20%.
```

Still not allowed:

```text
arbitrary graph scale accuracy
D-stage SSSP/end-to-end accuracy
cycle-accurate AXI/HBM/AXIS behavior
real dynamic graph workload holdout accuracy
```

## Next Step

The next validation step should move from synthetic maintenance-only cases to
larger holdouts:

1. Hot/cold mixed maintenance holdout.
2. Repeated update sequences that produce more complex level occupancy.
3. Real graph update batches as B-stage-only holdout if the host path can expose
   maintenance counters for those inputs.
4. Separate D-stage SSSP calibration after B-stage behavior remains stable.
