# D-Stage Phase 3A.4 Multi-Source Replay Validation

Date: 2026-07-19

## Goal

Calibrate the D-stage simulator for single-level L0 multi-source replay. This
phase extends Phase 3A.3 beyond one active source while still avoiding
multi-level state, hot/cold mixing, and real-graph workload complexity.

## Code Changes

HLS host repo:

- `/home/chuxiao/spine-dynamic-graph-reduce-levels/tests/test_integration/host_partitioned_csr_e2e_smoke.cpp`
  - Added `--multi-source-tile-work`.
  - Added `--striped-source-tile-work`.
  - Printed `active_record_replays` in the final smoke summary.

Simulator repo:

- `spine_cycle_sim/workloads/generators.py`
  - Added `generate_multi_source_tile_workload()`.
  - Added `generate_striped_source_tile_workload()`.
- `scripts/compare_dstage_tile_schedule.py`
  - Added schedule support for the new host scenarios.
  - Added strict counter comparison for reliable HW counters.
  - Kept known split-xclbin diagnostic counters separate.
- `scripts/run_hw_dstage_readiness.py`
  - Added matrices:
    - `phase3a4_replay_calibration`
    - `phase3a4_replay_holdout`
- `scripts/analyze_hw_dstage_tile_timing.py`
  - Added replay-sensitive features:
    - `active_records_x_touched_tiles`
    - `tile_max_work`
    - `tile_clipped_ranges`
  - Added `--weight-mode sqrt_relative` for percent-error-oriented fitting.

Related HLS host doc:

- `/home/chuxiao/spine-dynamic-graph-reduce-levels/docs/phase3a4_multi_source_replay_host_20260719.md`

## Commands

Host compile:

```bash
cd /home/chuxiao/spine-dynamic-graph-reduce-levels/tests/test_integration
make host_partitioned_csr_e2e_smoke
```

Python checks:

```bash
cd /home/chuxiao/spine-cycle-sim
python3 -m py_compile \
  spine_cycle_sim/workloads/generators.py \
  spine_cycle_sim/workloads/__init__.py \
  scripts/compare_dstage_tile_schedule.py \
  scripts/run_hw_dstage_readiness.py \
  scripts/analyze_hw_dstage_tile_timing.py

python3 -m unittest tests.test_dstage_tile_schedule tests.test_hw_dstage_readiness -v
```

Calibration:

```bash
python3 scripts/run_hw_dstage_readiness.py \
  --matrix phase3a4_replay_calibration \
  --out-dir results/dstage_phase3a4_replay_calibration_hw_20260719_155924 \
  --repeats 3 \
  --timeout 300
```

Calibration schedule/counter compare:

```bash
python3 scripts/compare_dstage_tile_schedule.py \
  --hw-dir results/dstage_phase3a4_replay_calibration_hw_20260719_155924
```

Holdout:

```bash
python3 scripts/run_hw_dstage_readiness.py \
  --matrix phase3a4_replay_holdout \
  --out-dir results/dstage_phase3a4_replay_holdout_hw_20260719_154734 \
  --repeats 3 \
  --timeout 300
```

Holdout schedule/counter compare:

```bash
python3 scripts/compare_dstage_tile_schedule.py \
  --hw-dir results/dstage_phase3a4_replay_holdout_hw_20260719_154734
```

Timing analysis:

```bash
python3 scripts/analyze_hw_dstage_tile_timing.py \
  --calibration-dir results/dstage_phase3a4_replay_calibration_hw_20260719_155924 \
  --holdout-dir results/dstage_phase3a4_replay_holdout_hw_20260719_154734 \
  --out-dir results/dstage_phase3a4_replay_analysis_weighted_20260719_160621 \
  --freq-mhz 134 \
  --alpha 1e-10 \
  --weight-mode sqrt_relative \
  --max-threshold-pct 20
```

## Evidence

xclbin:

```text
57f1459e53145f63e89845d7a694e52db548f90611d9d8cd665a413f67bf12a0
/data/feiyang/spine-dynamic-graph-builds/stream_sparse_carry_cursors_local_20260716_160954/compact_validation_20260717/hw_134_routed_accepted/xclbin/spine_partitioned_split_e2e.hw.xclbin
```

Instrumented host:

```text
aad70a399edec252f013f2094e7d1d5d6c62cb3825cecb3585359e70be49b5b4
/home/chuxiao/spine-dynamic-graph-reduce-levels/tests/test_integration/host_partitioned_csr_e2e_smoke
```

Results:

```text
Calibration HW:
  results/dstage_phase3a4_replay_calibration_hw_20260719_155924
  31 cases * 3 repeats = 93/93 PASS
  schedule_compare: PASS, schedule_samples=270, schedule_failures=0
  strict counter compare: PASS, counter_samples=93, counter_failures=0

Holdout HW:
  results/dstage_phase3a4_replay_holdout_hw_20260719_154734
  10 cases * 3 repeats = 30/30 PASS
  schedule_compare: PASS, schedule_samples=165, schedule_failures=0
  strict counter compare: PASS, counter_samples=30, counter_failures=0

Timing analysis:
  results/dstage_phase3a4_replay_analysis_weighted_20260719_160621
  calibration median abs error = 2.852%
  calibration max abs error    = 16.967%
  holdout median abs error     = 3.009%
  holdout max abs error        = 18.769%
  holdout within 10%           = 9/10
  holdout within 20%           = 10/10
```

## Main Findings

### 1. Replay pressure is a first-order D-stage cost

The important replay proxy is:

```text
active_records_x_touched_tiles = active_records * touched_tile_entries
```

This is not the same as edge count.

Examples:

```text
a4_calib_work_s4_w1024
  traversed_edges=4096
  active_records=4
  touched_tiles=1
  conv_span_ms=0.707809

a4_calib_boundary_s4097_w1
  traversed_edges=4097
  active_records=4097
  touched_tiles=1
  conv_span_ms=54.715
```

The edge counts differ by only one edge, but the second case has thousands of
active source records and crosses into full path. Runtime is about 77x larger.

### 2. Replay across many tiles can dominate even with few edges

```text
a4_hold_multitile_s96_t8
  traversed_edges=768
  active_records=96
  touched_tiles=8
  conv_span_ms=8.00857

a4_hold_replay_below_s4095_t16
  traversed_edges=4095
  active_records=4095
  touched_tiles=16
  conv_span_ms=433.376
```

The large case is dominated by reader/replay time, not by edge count.

### 3. Replay fallback boundary is visible in schedule and timing

At the threshold:

```text
a4_calib_replay_at_s4096_t16
  active_records_x_touched_tiles=65536
  fast_path_tiles=16
  full_path_tiles=0
  conv_span_ms=433.489
```

Just above the threshold:

```text
a4_calib_replay_above_s4097_t16
  active_records_x_touched_tiles=65552
  fast_path_tiles=0
  full_path_tiles=16
  conv_span_ms=506.637
```

The schedule reference marks fallback and the timing increases by about 73 ms.

## Counter Caveat

The current routed split xclbin does not expose all replay counters reliably in
the final `PARTITIONED_CSR_E2E_SMOKE` line. In particular, these fields are
diagnostic only for this xclbin:

- `marked_tiles`
- `fallback_used`
- `row_lookups`
- `clipped_ranges`
- `active_record_replays`
- `scattered_vertex_words`

Therefore Phase 3A.4 uses:

- host/simulator tile schedule comparison for structural replay and fallback
  evidence;
- reliable HW final counters for touched/fast/full/gathered/swept behavior;
- real HW `conv_span_ms` as the timing target.

## Current Scope

This phase is validated for:

- controlled synthetic L0-only D-stage workloads;
- cold destination partitions;
- multi-source replay;
- multi-tile and multi-partition replay;
- replay fallback boundary cases;
- the 134 MHz routed xclbin listed above.

It still does not claim full accuracy for:

- multi-level graph state;
- hot/cold mixed workloads;
- real graph workload distributions;
- cycle-accurate AXI outstanding / stream backpressure.
