# D-Stage Phase 3A.3 Multi-Tile / Multi-Partition Validation

Date: 2026-07-19

## Goal

Extend D-stage validation from two-tile synthetic cases to broader multi-tile
and multi-partition workloads, then check whether the simulator still matches
the current routed Spine hardware closely enough for bottleneck exploration.

This phase still focuses on one active source. Multi-source replay and
multi-level state are intentionally left for later phases.

## Code Changes

Edited:

- `spine_cycle_sim/workloads/generators.py`
  - Added `generate_partition_tile_workload()`.
  - Uses the same destination formula as the HLS host:

```text
dst = partition * vs_partition_size + tile * tile_vertices + 1 + i
```

- `spine_cycle_sim/workloads/__init__.py`
  - Exports `generate_partition_tile_workload()`.

- `scripts/compare_dstage_tile_schedule.py`
  - Added support for matrix cases using:

```bash
--partition-tile-work <p:w0,w1,...> [p:w0,w1,...]
```

- `scripts/run_hw_dstage_readiness.py`
  - Added matrices:
    - `phase3a3_tile_calibration`
    - `phase3a3_tile_holdout`

- `scripts/analyze_hw_dstage_tile_timing.py`
  - Added partition-level timing features:
    - `tile_partition_count`
    - `tile_multi_partition`
    - `tile_max_partition_work`
    - `tile_max_partition_swept_words`
    - `tile_max_partition_tile_count`

- `tests/test_dstage_tile_schedule.py`
  - Added a multi-partition schedule test.

- `tests/test_hw_dstage_readiness.py`
  - Added matrix coverage checks for Phase 3A.3.

Related HLS host doc:

- `/home/chuxiao/spine-dynamic-graph-reduce-levels/docs/phase3a3_partition_tile_work_host_20260719.md`

## Build And Test Commands

Python checks:

```bash
cd /home/chuxiao/spine-cycle-sim
python3 -m py_compile \
  spine_cycle_sim/workloads/generators.py \
  spine_cycle_sim/workloads/__init__.py \
  scripts/compare_dstage_tile_schedule.py \
  scripts/analyze_hw_dstage_tile_timing.py \
  scripts/run_hw_dstage_readiness.py

python3 -m unittest \
  tests.test_dstage_tile_schedule \
  tests.test_hw_dstage_readiness \
  -v
```

HLS host compile:

```bash
cd /home/chuxiao/spine-dynamic-graph-reduce-levels/tests/test_integration
make host_partitioned_csr_e2e_smoke
```

Calibration HW run:

```bash
cd /home/chuxiao/spine-cycle-sim
python3 scripts/run_hw_dstage_readiness.py \
  --matrix phase3a3_tile_calibration \
  --out-dir results/dstage_phase3a3_tile_calibration_hw_20260719_120736 \
  --repeats 3 \
  --timeout 300
```

Calibration schedule compare:

```bash
python3 scripts/compare_dstage_tile_schedule.py \
  --hw-dir results/dstage_phase3a3_tile_calibration_hw_20260719_120736
```

Holdout HW run:

```bash
python3 scripts/run_hw_dstage_readiness.py \
  --matrix phase3a3_tile_holdout \
  --out-dir results/dstage_phase3a3_tile_holdout_hw_20260719_121001 \
  --repeats 3 \
  --timeout 300
```

Holdout schedule compare:

```bash
python3 scripts/compare_dstage_tile_schedule.py \
  --hw-dir results/dstage_phase3a3_tile_holdout_hw_20260719_121001
```

Timing analysis:

```bash
python3 scripts/analyze_hw_dstage_tile_timing.py \
  --calibration-dir results/dstage_phase3a3_tile_calibration_hw_20260719_120736 \
  --holdout-dir results/dstage_phase3a3_tile_holdout_hw_20260719_121001 \
  --out-dir results/dstage_phase3a3_tile_analysis_20260719_121139 \
  --freq-mhz 134 \
  --max-threshold-pct 20
```

## Evidence

Hardware xclbin:

```text
57f1459e53145f63e89845d7a694e52db548f90611d9d8cd665a413f67bf12a0
/data/feiyang/spine-dynamic-graph-builds/stream_sparse_carry_cursors_local_20260716_160954/compact_validation_20260717/hw_134_routed_accepted/xclbin/spine_partitioned_split_e2e.hw.xclbin
```

Instrumented host:

```text
9f9c3560420f96737bbb46205b6daafd5e7677f31137afca532ff3b25ba9830f
/home/chuxiao/spine-dynamic-graph-reduce-levels/tests/test_integration/host_partitioned_csr_e2e_smoke
```

Results:

```text
Calibration HW:
  results/dstage_phase3a3_tile_calibration_hw_20260719_120736
  12 cases * 3 repeats = 36/36 PASS
  schedule_compare: PASS, samples=132, failures=0

Holdout HW:
  results/dstage_phase3a3_tile_holdout_hw_20260719_121001
  8 cases * 3 repeats = 24/24 PASS
  schedule_compare: PASS, samples=87, failures=0

Timing analysis:
  results/dstage_phase3a3_tile_analysis_20260719_121139
  calibration median abs error = 0.035%
  calibration max abs error    = 0.275%
  holdout median abs error     = 0.568%
  holdout max abs error        = 8.638%
  holdout within 10%           = 8/8
  holdout within 20%           = 8/8
```

## What This Shows

1. Schedule structure is now aligned for controlled multi-tile and
   multi-partition one-source workloads. The simulator matches HW on partition,
   tile id, tile size, tile work, fast/full path, gathered words, swept words,
   and scattered words.

2. The tile-level timing model generalizes beyond the Phase 3A.2 two-tile
   cases. It covers:
   - More than two active tiles in one partition.
   - Multiple destination partitions.
   - Boundary points around 4095 / 4096 / 4097 / 4098.
   - Larger full-tile work such as 16K / 32K / 49K edges.

3. The current D-stage bottleneck signal is not just edge count. Full-path
   swept vertex words and reader time are often dominant. For example:
   - `a3_hold_mt_4098_8192_16384`: 28,674 traversed edges, 3 full tiles,
     median `conv_span_ms=22.8786`, `reader_ms=19.0204`.
   - `a3_hold_mt_128_4095_16384_49152`: 69,759 traversed edges, 2 fast and
     2 full tiles, median `conv_span_ms=23.379`, `reader_ms=13.0146`.

4. Multi-partition does not automatically mean worse timing for these
   controlled one-source cases. Cases with similar tile schedule counters often
   have similar timing whether the tiles are in one partition or split across
   partitions. This suggests the schedule/tile path shape is the first-order
   factor for the current tested range.

## Current Limits

- This does not yet calibrate multi-source replay.
- This does not yet calibrate multi-level graph state.
- The memory/stream model is still feature-calibrated from HW timings rather
  than cycle-accurately modeling AXI outstanding requests and backpressure.
- Results are valid for the current 134 MHz routed xclbin and host
  instrumentation listed above.
