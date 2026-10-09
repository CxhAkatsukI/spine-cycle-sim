# D-Stage Phase 3B Bottleneck Profiling

Date: 2026-07-19

## Goal

Use the Phase 3A.4 D-stage timing model as a frozen predictor and stress-test
it on a broader workload matrix. This phase is not a refit. It asks:

- which synthetic regimes still match the routed HW;
- where the model first becomes untrusted;
- whether the end-to-end kernel time is dominated by maintenance or D-stage;
- what the next modeling priority should be.

## Scope

Fixed HW:

```text
57f1459e53145f63e89845d7a694e52db548f90611d9d8cd665a413f67bf12a0
/data/feiyang/spine-dynamic-graph-builds/stream_sparse_carry_cursors_local_20260716_160954/compact_validation_20260717/hw_134_routed_accepted/xclbin/spine_partitioned_split_e2e.hw.xclbin
```

Host executable:

```text
aad70a399edec252f013f2094e7d1d5d6c62cb3825cecb3585359e70be49b5b4
/home/chuxiao/spine-dynamic-graph-reduce-levels/tests/test_integration/host_partitioned_csr_e2e_smoke
```

Frozen D-stage model:

```text
results/dstage_phase3a4_replay_analysis_weighted_20260719_160621/fit.json
```

The first Phase 3B run uses controlled synthetic workloads. Real graph sanity
checks are still blocked at the current host level because
`host_partitioned_csr_e2e_smoke` has no `.mtx` or edge-list input path.

## Code Changes

- `scripts/run_hw_dstage_readiness.py`
  - Added `phase3b_bottleneck_synthetic`.
  - Added `phase3b_multibatch_probe`.
  - Added `batch_events.csv` output from `PARTITIONED_CSR_E2E_BATCH`.
  - Added `target_level` to summary aggregation.
- `scripts/analyze_phase3b_bottlenecks.py`
  - Applies a frozen Phase 3A.4 D-stage model to a new HW result directory.
  - Emits `predictions.csv`, `bottleneck_report.csv`, `sweep_summary.csv`,
    and `summary.json`.
  - Classifies trusted/borderline/untrusted cases and likely gap class.
- `scripts/compare_dstage_tile_schedule.py`
  - Accepts split-CU `swept_vertex_words` in the same range as the HLS host:
    load-only through load-plus-store.
- Tests:
  - `tests/test_hw_dstage_readiness.py`
  - `tests/test_phase3b_bottlenecks.py`
  - `tests/test_dstage_schedule_compare.py`

## Commands

Synthetic broad matrix:

```bash
cd /home/chuxiao/spine-cycle-sim
python3 scripts/run_hw_dstage_readiness.py \
  --matrix phase3b_bottleneck_synthetic \
  --out-dir results/phase3b_bottleneck_synthetic_hw_20260719_172739 \
  --repeats 3 \
  --timeout 300
```

Schedule/counter compare:

```bash
python3 scripts/compare_dstage_tile_schedule.py \
  --hw-dir results/phase3b_bottleneck_synthetic_hw_20260719_172739
```

Bottleneck report:

```bash
python3 scripts/analyze_phase3b_bottlenecks.py \
  --hw-dir results/phase3b_bottleneck_synthetic_hw_20260719_172739 \
  --out-dir results/phase3b_bottleneck_synthetic_analysis_20260719_173050
```

Multibatch diagnostic probe:

```bash
python3 scripts/run_hw_dstage_readiness.py \
  --matrix phase3b_multibatch_probe \
  --out-dir results/phase3b_multibatch_probe_hw_20260719_173438 \
  --repeats 3 \
  --timeout 300

python3 scripts/analyze_phase3b_bottlenecks.py \
  --hw-dir results/phase3b_multibatch_probe_hw_20260719_173438 \
  --out-dir results/phase3b_multibatch_probe_analysis_20260719_173540
```

Tests:

```bash
python3 -m py_compile \
  scripts/run_hw_dstage_readiness.py \
  scripts/compare_dstage_tile_schedule.py \
  scripts/analyze_phase3b_bottlenecks.py

python3 -m unittest discover -s tests -v
```

## Evidence

Synthetic broad matrix:

```text
22 cases * 3 repeats = 66/66 PASS
schedule_compare: PASS
schedule_samples=390
schedule_failures=0
counter_samples=66
counter_failures=0
```

D-stage prediction report:

```text
samples=22
median_abs_pct_error=6.500%
max_abs_pct_error=61.575%
within_10_pct=12/22
within_20_pct=16/22
trusted=16
borderline=1
untrusted=5
```

Bottleneck labels:

```text
maintenance_dominant=10
dstage_reader_dominant=6
dstage_reader_replay_dominant=3
dstage_compute_or_fixed_dominant=1
balanced_or_small_fixed=2
```

Gap labels:

```text
within_current_dstage_model=16
large_full_tile_low_replay_gap=2
multi_partition_interaction_gap=3
small_multitile_fixed_overhead_gap=1
```

Multibatch diagnostic:

```text
4 cases * 3 repeats = 12/12 PASS
trusted_status=diagnostic_out_of_scope for all 4 cases
median_abs_pct_error=392.288%
max_abs_pct_error=711.407%
```

## Key Cases

| case | edges | records | tiles | fast | full | maint_ms | dstage_ms | abs_err | status | gap |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---|---|
| p3b_replay_below_s2048_t16 | 2048 | 2048 | 16 | 16 | 0 | 4.269 | 216.922 | 0.005% | trusted | within_current_dstage_model |
| p3b_replay_below_s4094_t16 | 4094 | 4094 | 16 | 16 | 0 | 8.205 | 433.282 | 0.109% | trusted | within_current_dstage_model |
| p3b_replay_above_s4098_t16 | 4098 | 4098 | 16 | 0 | 16 | 8.286 | 506.757 | 0.005% | trusted | within_current_dstage_model |
| p3b_replay_at_s8192_t8 | 8192 | 8192 | 8 | 8 | 0 | 16.132 | 460.935 | 0.850% | trusted | within_current_dstage_model |
| p3b_replay_above_s8193_t8 | 8193 | 8193 | 16 | 0 | 16 | 16.166 | 891.301 | 5.309% | trusted | within_current_dstage_model |
| p3b_full_boundary_s31_w133 | 4123 | 31 | 1 | 0 | 1 | 8.272 | 1.964 | 31.817% | untrusted | large_full_tile_low_replay_gap |
| p3b_full_large_s32_w1024 | 32768 | 32 | 1 | 0 | 1 | 63.683 | 2.497 | 61.575% | untrusted | large_full_tile_low_replay_gap |
| p3b_multipart_s96_mixed | 11232 | 288 | 5 | 4 | 1 | 59.094 | 15.751 | 56.307% | untrusted | multi_partition_interaction_gap |

## Conclusions

### 1. Replay/fallback generalizes well

The replay-heavy boundary cases remain accurate without refitting. The model
captures the important jump:

```text
p3b_replay_below_s4094_t16:
  records * tiles = 4094 * 16 = 65504
  fast tiles = 16
  D-stage = 433.282 ms
  error = 0.109%

p3b_replay_above_s4098_t16:
  records * tiles = 4098 * 16 = 65568
  full tiles = 16
  D-stage = 506.757 ms
  error = 0.005%
```

The stronger eight-tile case also confirms the fallback behavior:

```text
p3b_replay_at_s8192_t8:
  records * tiles = 8192 * 8 = 65536
  touched tiles = 8
  D-stage = 460.935 ms

p3b_replay_above_s8193_t8:
  records * discovered tiles = 8193 * 8 > 65536
  fallback touches all 16 valid tiles
  D-stage = 891.301 ms
```

So the current simulator is credible for controlled L0 replay/fallback timing.

### 2. Edge count is still not the right mental model

Only 2048 edges can take 216.922 ms when they imply many record/tile replays.
Meanwhile 32768 edges in a single low-replay full tile takes only 2.497 ms in
D-stage, although maintenance takes 63.683 ms. The bottleneck changes with
distribution, not just size.

### 3. The first synthetic gaps are not replay

The broad matrix found the next likely D-stage model gaps:

- large full tile with low replay;
- multi-partition interaction;
- small multi-tile fixed overhead.

These were underrepresented in the Phase 3A.4 calibration matrix, which focused
on multi-source replay.

### 4. End-to-end bottleneck is often maintenance

10 of 22 synthetic cases are `maintenance_dominant`. This does not mean the
D-stage model error is caused by maintenance. It means a performance report
must show both:

- D-stage prediction error;
- end-to-end stage shares.

Otherwise a slow case can be misdiagnosed.

### 5. Multibatch/level-state is out of scope for the current D-stage model

The multibatch diagnostic cases all pass HW functionally, but all are marked
`diagnostic_out_of_scope`. Example:

| case | batches | final target | edges | maint_ms | dstage_ms | abs_err | status |
|---|---:|---:|---:|---:|---:|---:|---|
| p3b_repeat_fanout_e512_b2_s64 | 2 | 1 | 1024 | 25.539 | 13.589 | 701.28% | diagnostic_out_of_scope |
| p3b_repeat_fanout_e1024_b3_s64 | 3 | 0 | 3072 | 77.928 | 40.051 | 711.41% | diagnostic_out_of_scope |
| p3b_repeat_star_dense_e512_b2 | 2 | 1 | 1024 | 24.919 | 1.099 | 60.93% | diagnostic_out_of_scope |
| p3b_repeat_star_e1024_b3 | 3 | 0 | 3072 | 76.573 | 1.683 | 83.29% | diagnostic_out_of_scope |

`target_level` above is the final batch target. Use `batch_events.csv` for the
full per-batch level/carry sequence.

## Current Trusted Claims

Safe to claim:

- Controlled L0 replay/fallback behavior is captured well.
- The simulator correctly predicts the large replay threshold jump in the
  tested synthetic range.
- Current broad synthetic testing identifies maintenance as the end-to-end
  bottleneck in many small/low-D-stage cases.
- The next D-stage modeling gaps are full-tile low-replay and multi-partition
  interactions.

Not safe to claim yet:

- Accuracy for multibatch or multi-level graph state.
- Accuracy for hot/cold mixed state.
- Accuracy for real graph distributions.
- Cycle-accurate AXI/stream/backpressure behavior.
- A final Spine-vs-other-accelerator performance conclusion.

## Next Priority

Phase 3C should repair the first real broad-matrix gaps:

1. Add calibration/validation points for low-replay large full tiles.
2. Add multi-partition interaction features or a better per-partition timing
   decomposition.
3. Then build a real graph input path for the host so real `.mtx` sanity checks
   can be run without changing the HW xclbin.

