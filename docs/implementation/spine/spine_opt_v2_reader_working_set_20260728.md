# Spine opt-v2: finite reader working set

Date: 2026-07-28  
Simulator branch: `codex/deltahls-paper-optimization`  
HLS branch: `codex/source-page-working-set-cache`

## Change

Opt-v2 keeps the ratio-2 hierarchy, 16 destination partitions, exact/fallback
tile paths, update semantics, and algorithm arithmetic unchanged. It adds two
bounded mechanisms on top of opt-v1:

1. the exact-path active-record gate grows from 16,384 to 32,768 records; and
2. each fixed family invocation gets an 11-entry source-page cache, one entry
   per level, holding an epoch, four 64-bit bitmap words, and a page base.

The cache is cleared at each fixed-family invocation or fallback tile pass. It
is therefore finite hardware state, not an ideal or unbounded simulator cache.
The larger active working set costs 393,216 additional logical on-chip bytes.

## Controlled results

All rows pass the architecture-precision and independent mathematical oracles,
emit the same edge count, and close reader, compute, and aggregate memory
ledgers.

| Workload and A/B | Parent cycles | Opt-v2 cycles | Speedup |
|---|---:|---:|---:|
| Compact exact path, source-page cache only | 210,025 | 184,060 | 1.141x |
| Forced fallback, source-page cache only | 331,173 | 277,808 | 1.192x |
| Amazon 50K, 16K gate to 32K gate | 101,674,004 | 25,518,259 | 3.984x |
| Amazon 50K, gate plus source-page cache | 101,674,004 | 15,145,344 | 6.713x |

On the 50K-edge full-PageRank slice, backend requests fall from 4,917,578 to
984,080. The 19,058 active records force fallback under the parent gate but fit
the optimized exact path. Within the optimized exact path, the finite page
cache records 43,047 hits, 1,213 misses, and 1,213 fills.

The 50K speedup is intentionally reported as an ablation, not as a geometric
mean for the three-algorithm paper matrix. It applies to broad frontiers that
cross the old active-record gate; sparse weighted SSSP normally does not obtain
this gain.

## Formal K=1 comparison

The frozen exact-idle matrix contains 73 architecture pairs and 146 system
runs. Every row passes both numerical oracles and all request-conservation
checks. It covers weighted SSSP, full PageRank, thresholded residual PageRank,
four dynamic weighted-SSSP cases, calibration/holdout workloads, 4095/4096/4097
boundaries, skew, hub, fan-in, dangling, and three real compact slices.

| Population | Pairs | Spine wins | GraSU+ReGraph wins | Spine speedup geomean |
|---|---:|---:|---:|---:|
| All rows | 73 | 48 | 25 | 2.117x |
| Full PageRank | 23 | 14 | 9 | 2.746x |
| Residual PageRank | 23 | 16 | 7 | 3.315x |
| Weighted SSSP | 23 | 14 | 9 | 1.106x |
| Dynamic weighted SSSP | 4 | 4 | 0 | 1.514x |
| Real compact slices only | 9 | 5 | 4 | 1.119x |

The real compact subset is the conservative result: residual PageRank wins on
all three slices (1.743x geomean), full PageRank is 1.291x by geomean but wins
only one of three slices, and weighted SSSP is 0.623x. The all-row mean is
synthetic-heavy and must not replace the real-data result in a headline claim.

## HLS feasibility

The optimized read-maintenance CU compiles to RTL and Vitis HLS infers the
required four-word bitmap burst. Relative to opt-v1, the 300 MHz-target focused
synthesis reports:

| Resource | opt-v1 | opt-v2 | Delta |
|---|---:|---:|---:|
| BRAM18K | 98 | 98 | 0 |
| DSP | 20 | 20 | 0 |
| FF | 134,596 | 146,499 | +11,903 |
| LUT | 203,725 | 222,881 | +19,156 |
| URAM | 84 | 100 | +16 |

The 300 MHz-target schedule estimates 7.942 ns (125.9 MHz), so it does not
close 3.333 ns. A separate 150 MHz-target synthesis chooses a lower-register
schedule and estimates 12.809 ns (78.1 MHz), also missing its target. These are
resource and RTL-generation gates, not timing closure. A full 150 MHz U55C
place-and-route is the remaining timing authority.

## Reproduction

Rebuild the fail-closed optimization evidence:

```bash
cd /home/chuxiao/spine-cycle-sim-publication
cmake --build build/cycle-core -j 8
python3 scripts/analyze_spine_opt_v2.py \
  --exact-parent /data/tmp/chuxiao/spine_opt_v2_ab_exact_parent_20260728/summary.json \
  --exact-cache /data/tmp/chuxiao/spine_opt_v2_profile_smoke_20260728/summary.json \
  --fallback-parent /data/tmp/chuxiao/spine_opt_v2_ab_fallback_parent_cold_20260728/summary.json \
  --fallback-cache /data/tmp/chuxiao/spine_opt_v2_ab_fallback_cache_cold_20260728/summary.json \
  --large-parent /data/tmp/chuxiao/spine_candidate10_opt_v2_native_gate_parent_amazon50k_exact_idle_20260728/summary.json \
  --large-gate /data/tmp/chuxiao/spine_candidate10_opt_v2_gate_only_amazon50k_20260728/summary.json \
  --large-combined /data/tmp/chuxiao/spine_candidate10_opt_v2_amazon50k_20260728/summary.json \
  --parent-csynth /home/chuxiao/spine-dynamic-graph-opt-v1/tests/test_integration/csynth_readmaint_prj/sol/syn/report/spine_partconv_rdmaint_kernel_csynth.rpt \
  --optimized-csynth /home/chuxiao/spine-dynamic-graph-opt-v2/tests/test_integration/csynth_readmaint_prj/sol/syn/report/spine_partconv_rdmaint_kernel_csynth.rpt \
  --optimized-csynth-150 /home/chuxiao/spine-dynamic-graph-opt-v2/tests/test_integration/csynth_readmaint_150mhz_prj/sol/syn/report/spine_partconv_rdmaint_kernel_csynth.rpt \
  --optimized-csynth-log /data/tmp/chuxiao/optv2_csynth_20260728.log \
  --core-test-bin build/cycle-core/cpp/spine_cycle_core_tests \
  --output docs/evidence/spine_opt_v2_reader_working_set_20260728.json
```

Re-analyze the formal matrix:

```bash
python3 scripts/analyze_shared_comparison_matrix.py \
  --matrix-dir /data/tmp/chuxiao/candidate10_opt_v2_k1_formal_matrix_exact_idle_20260728 \
  --out-dir /data/tmp/chuxiao/candidate10_opt_v2_k1_formal_matrix_exact_idle_20260728/analysis
```

## Claim boundary

Opt-v2 is a correctness-preserving, bounded projected optimization with HLS RTL
and resource evidence. It is not yet a routed optimized FPGA implementation.
The current formal matrix proves compact and targeted behavior; broader real
multi-partition, dense-batch, sensitivity, on-chip energy, and routed timing
remain separate acceptance gates.
