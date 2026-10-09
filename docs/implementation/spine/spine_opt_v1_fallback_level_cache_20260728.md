# Spine opt-v1: fallback launch-level cache reuse

Date: 2026-07-28  
Simulator branch: `codex/deltahls-paper-optimization`  
HLS branch: `codex/fallback-level-cache-reuse`

## Scope

The candidate10 reader already loads the immutable family/level directory into
an on-chip launch cache for the exact range-task path. When the number of
active source records exceeds `range_task_active_gate`, the fallback path in
the baseline rereads those same level descriptors for each active source. The
optimization reuses the existing launch cache in fallback discovery and emit.

The page epoch, source bitmap, page base, row offset, and edge payload remain
execution-driven memory requests. The ratio-2 hierarchy, 16 destination
partitions, source ordering, latest-view resolver, active-source rule, tile
format, and algorithm arithmetic are unchanged. This is therefore a bounded
metadata-reuse optimization, not a flat graph snapshot or ideal cache.

## Result

The primary controlled SST A/B uses one compact real Amazon topology with
1,280 initial edges plus eight inserts. The active gate is set to 127 so that
128 active records force the same active-capacity fallback in both runs.

| Metric | candidate10 baseline | opt-v1 | Change |
|---|---:|---:|---:|
| Simulated E2E cycles | 839,404 | 331,173 | 2.535x faster |
| Backend requests | 51,079 | 24,511 | 52.0% fewer |
| Reader metadata bytes | 76,112 | 5,264 | 93.1% fewer |
| Reader requests | 13,239 | 4,377 | 66.9% fewer |
| Reader edges | 1,288 | 1,288 | identical |
| Architecture/math mismatches | 0 / 0 | 0 / 0 | pass |

The focused 129-vertex ring microbenchmark reports 120,084 versus 46,041
cycles (2.608x), 16,028 versus 7,100 backend requests, identical ranks, and
identical 129-edge work.

The non-fallback control sets the gate to 128. Because 128 active records do
not satisfy the HLS `active_count > gate` condition, both runs take exact path
1. Baseline and opt-v1 are cycle- and request-identical at 210,025 cycles and
22,609 backend requests. This closes the regression boundary: the feature is
inactive outside fallback.

## HLS evidence

HLS C simulation passes the dirty-frontier test and split-versus-monolithic
equivalence, including a 16,385-active-record case that crosses the native
16,384 gate. Final state, active output, edge stream, and overflow behavior all
match.

The baseline and optimized reader/maintenance top were synthesized with the
same Vitis HLS 2024.1 Tcl, U55C part, and 3.33 ns target:

| Resource/timing | baseline | opt-v1 | Delta |
|---|---:|---:|---:|
| BRAM18K | 98 | 98 | 0 |
| DSP | 20 | 20 | 0 |
| FF | 136,309 | 134,596 | -1,713 |
| LUT | 207,243 | 203,725 | -3,518 |
| URAM | 84 | 84 | 0 |
| Estimated period | 7.942 ns | 7.942 ns | 0 |

This passes the resource-feasibility gate: the optimization adds no memory or
DSP and does not degrade the top-level synthesis estimate. It does **not**
claim timing closure. Both versions miss the aggressive 3.33 ns focused-top
target, and integrated placement/routing remains pending.

## Reproduction

Build and run the simulator microbenchmark:

```bash
cd /home/chuxiao/spine-cycle-sim-publication
cmake --build build -j --target spine_cycle_core_tests spine_sst
build/cpp/spine_cycle_core_tests spine_pagerank_fallback_level_cache_reuse
```

The exact SST commands are represented by the four input summary hashes in
`docs/evidence/spine_opt_v1_fallback_level_cache_20260728.json`. Rebuild the
fail-closed evidence manifest after producing those summaries and csynth
reports:

```bash
cd /home/chuxiao/spine-cycle-sim-publication
python3 scripts/analyze_spine_opt_v1.py \
  --fallback-baseline /data/tmp/chuxiao/spine_opt_v1_sst_ab_base_v3_20260728/summary.json \
  --fallback-optimized /data/tmp/chuxiao/spine_opt_v1_sst_ab_opt_v3_20260728/summary.json \
  --control-baseline /data/tmp/chuxiao/spine_opt_v1_sst_ab_base_v2_20260728/summary.json \
  --control-optimized /data/tmp/chuxiao/spine_opt_v1_sst_ab_opt_v2_20260728/summary.json \
  --baseline-csynth /home/chuxiao/spine-dynamic-graph-baseline-csynth/tests/test_integration/csynth_readmaint_prj/sol/syn/report/spine_partconv_rdmaint_kernel_csynth.rpt \
  --optimized-csynth /home/chuxiao/spine-dynamic-graph-opt-v1/tests/test_integration/csynth_readmaint_prj/sol/syn/report/spine_partconv_rdmaint_kernel_csynth.rpt \
  --core-test-bin build/cpp/spine_cycle_core_tests \
  --output docs/evidence/spine_opt_v1_fallback_level_cache_20260728.json
```

Run the HLS semantic gates and focused synthesis:

```bash
cd /home/chuxiao/spine-dynamic-graph-opt-v1
make -C tests/test_integration \
  host_partitioned_dirty_frontier_test \
  host_partitioned_split_equivalence_test
tests/test_integration/host_partitioned_dirty_frontier_test
tests/test_integration/host_partitioned_split_equivalence_test
cd tests/test_integration
/data/yxx/tools/xilinx/Vitis_HLS/2024.1/bin/vitis_hls \
  -f csynth_readmaint_gate.tcl
```

## Claim boundary

Opt-v1 is expected to help only active-capacity fallback, especially broad
PageRank frontiers. It is not expected to improve sparse exact-path weighted
SSSP. The 2.535x number is a calibration result, not a paper holdout result and
not the final three-algorithm geometric mean. The profile stays projected until
the frozen holdout, sensitivity, and routed implementation gates are complete.
