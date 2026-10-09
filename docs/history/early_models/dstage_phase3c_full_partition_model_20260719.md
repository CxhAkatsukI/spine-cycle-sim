# D-Stage Phase 3C Full-Tile and Partition Model

Date: 2026-07-19

## Goal

Repair the first synthetic gaps found in Phase 3B without changing HLS or
rebuilding the xclbin. Phase 3C targets:

- large full tile with low replay;
- multi-partition interaction;
- small multi-tile fixed overhead.

Multibatch, multi-level, hot/cold, real graph input, and AXI/stream modeling
remain out of scope.

## Fixed HW

```text
57f1459e53145f63e89845d7a694e52db548f90611d9d8cd665a413f67bf12a0
/data/feiyang/spine-dynamic-graph-builds/stream_sparse_carry_cursors_local_20260716_160954/compact_validation_20260717/hw_134_routed_accepted/xclbin/spine_partitioned_split_e2e.hw.xclbin

aad70a399edec252f013f2094e7d1d5d6c62cb3825cecb3585359e70be49b5b4
/home/chuxiao/spine-dynamic-graph-reduce-levels/tests/test_integration/host_partitioned_csr_e2e_smoke
```

## Code Changes

- `scripts/run_hw_dstage_readiness.py`
  - Added `phase3c_full_partition_calibration`.
  - Added `phase3c_full_partition_holdout`.
  - Added `phase3c_final_validation`.
- `scripts/analyze_hw_dstage_tile_timing.py`
  - Allows multiple `--calibration-dir` arguments.
  - Adds full/partition-sensitive features:
    - `fast_records_x_tiles`
    - `full_records_x_tiles`
    - `partition_count_x_active_records`
    - `tile_partition_count`
    - `tile_multi_partition`
    - `tile_max_partition_work`
    - `tile_max_partition_swept_words`
    - `tile_mixed_path`
    - `full_work_per_active_record`
    - `full_work_per_full_tile`
- Tests:
  - `tests/test_hw_dstage_readiness.py`
  - `tests/test_dstage_tile_timing_features.py`

## Commands

Calibration HW:

```bash
cd /home/chuxiao/spine-cycle-sim
python3 scripts/run_hw_dstage_readiness.py \
  --matrix phase3c_full_partition_calibration \
  --out-dir results/phase3c_full_partition_calibration_hw_20260719_175201 \
  --repeats 3 \
  --timeout 300

python3 scripts/compare_dstage_tile_schedule.py \
  --hw-dir results/phase3c_full_partition_calibration_hw_20260719_175201
```

Holdout HW:

```bash
python3 scripts/run_hw_dstage_readiness.py \
  --matrix phase3c_full_partition_holdout \
  --out-dir results/phase3c_full_partition_holdout_hw_20260719_175623 \
  --repeats 3 \
  --timeout 300

python3 scripts/compare_dstage_tile_schedule.py \
  --hw-dir results/phase3c_full_partition_holdout_hw_20260719_175623
```

Fit with Phase 3A.4 replay calibration plus Phase 3C calibration:

```bash
python3 scripts/analyze_hw_dstage_tile_timing.py \
  --calibration-dir results/dstage_phase3a4_replay_calibration_hw_20260719_155924 \
  --calibration-dir results/phase3c_full_partition_calibration_hw_20260719_175201 \
  --holdout-dir results/phase3c_full_partition_holdout_hw_20260719_175623 \
  --out-dir results/phase3c_full_partition_analysis_20260719_175848 \
  --freq-mhz 134 \
  --alpha 1e-10 \
  --weight-mode sqrt_relative \
  --max-threshold-pct 20
```

Phase 3B final validation with the new model:

```bash
python3 scripts/analyze_phase3b_bottlenecks.py \
  --hw-dir results/phase3b_bottleneck_synthetic_hw_20260719_172739 \
  --model-fit results/phase3c_full_partition_analysis_20260719_175848/fit.json \
  --out-dir results/phase3c_phase3b_final_report_20260719_175900
```

Replay guard:

```bash
python3 scripts/analyze_hw_dstage_tile_timing.py \
  --calibration-dir results/dstage_phase3a4_replay_calibration_hw_20260719_155924 \
  --calibration-dir results/phase3c_full_partition_calibration_hw_20260719_175201 \
  --holdout-dir results/dstage_phase3a4_replay_holdout_hw_20260719_154734 \
  --out-dir results/phase3c_replay_guard_analysis_20260719_175900 \
  --freq-mhz 134 \
  --alpha 1e-10 \
  --weight-mode sqrt_relative \
  --max-threshold-pct 20
```

Exact final rerun:

```bash
python3 scripts/run_hw_dstage_readiness.py \
  --matrix phase3c_final_validation \
  --out-dir results/phase3c_final_validation_hw_20260719_175901 \
  --repeats 3 \
  --timeout 300

python3 scripts/compare_dstage_tile_schedule.py \
  --hw-dir results/phase3c_final_validation_hw_20260719_175901

python3 scripts/analyze_phase3b_bottlenecks.py \
  --hw-dir results/phase3c_final_validation_hw_20260719_175901 \
  --model-fit results/phase3c_full_partition_analysis_20260719_175848/fit.json \
  --out-dir results/phase3c_final_validation_analysis_20260719_180100
```

Tests:

```bash
python3 -m unittest discover -s tests -v
```

## Evidence

Schedule/counter checks:

```text
Calibration:
  23 cases * 3 repeats = 69/69 PASS
  schedule_samples=177
  schedule_failures=0
  counter_samples=69
  counter_failures=0

Holdout:
  12 cases * 3 repeats = 36/36 PASS
  schedule_samples=114
  schedule_failures=0
  counter_samples=36
  counter_failures=0

Final validation:
  8 cases * 3 repeats = 24/24 PASS
  schedule_samples=189
  schedule_failures=0
  counter_samples=24
  counter_failures=0
```

Timing fit:

```text
Calibration:
  samples=54
  median_abs_pct_error=2.383%
  max_abs_pct_error=12.379%
  within_20=54/54

Phase 3C holdout:
  samples=12
  median_abs_pct_error=3.552%
  max_abs_pct_error=18.152%
  within_10=11/12
  within_20=12/12

Phase 3B broad final report:
  samples=22
  median_abs_pct_error=5.282%
  max_abs_pct_error=17.800%
  trusted=22/22

Replay guard:
  samples=10
  median_abs_pct_error=3.160%
  max_abs_pct_error=10.782%
  within_20=10/10

Exact final rerun:
  samples=8
  median_abs_pct_error=1.949%
  max_abs_pct_error=6.837%
  trusted=8/8
```

## Before / After on Phase 3B Failures

| case | Phase 3B abs err | old status | Phase 3C abs err | new status |
|---|---:|---|---:|---|
| p3b_full_boundary_s31_w133 | 31.817% | untrusted | 4.216% | trusted |
| p3b_full_large_s32_w1024 | 61.575% | untrusted | 3.325% | trusted |
| p3b_multitile_s16_mixed | 32.597% | untrusted | 6.348% | trusted |
| p3b_multipart_s32_p0_p7_p15 | 50.258% | untrusted | 0.420% | trusted |
| p3b_multipart_s96_mixed | 56.307% | untrusted | 1.884% | trusted |

The exact final rerun gives the same conclusion, with max error 6.837%.

## Main Finding

Phase 3B was not telling us that replay modeling was broken. It was telling us
that the old timing model mixed several different full-path regimes together.

Two cases with the same edge count can behave differently:

```text
p3c_cal_full_s1_w32768:
  one source, 32768 edges, one full tile
  conv_ms ~= 8.58

p3c_cal_full_s8_w4096:
  eight sources, 32768 edges, one full tile
  conv_ms ~= 2.61
```

So full-tile cost depends on source/row shape and not just total full-tile edge
work. The new ratio features capture this shape.

For multi-partition cases, the important fix is that global sums are not enough.
The model now sees partition count and max-per-partition pressure, which lets it
distinguish one large partition from several smaller active partitions.

## Current Trusted Scope

Safe to claim after Phase 3C:

- Controlled L0 replay/fallback remains accurate.
- Large full-tile low-replay synthetic cases are now modeled.
- Multi-partition synthetic interactions are now modeled.
- Phase 3B broad synthetic matrix is fully trusted under the current threshold.

Still not safe to claim:

- multibatch / multi-level accuracy;
- hot/cold mixed graph state accuracy;
- real graph workload accuracy;
- cycle-accurate AXI/stream/backpressure behavior;
- final cross-accelerator performance claims.

## Next Priority

The next meaningful stage is no longer another synthetic L0 fix. Phase 3D should
either:

1. build a real graph input path for host/simulator sanity checks; or
2. start modeling multibatch / multi-level D-stage state.

The right choice depends on whether we want the next milestone to be
workload-realism evidence or deeper architecture-state accuracy.

