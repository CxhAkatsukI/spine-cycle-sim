# RQ3 Realized-Work and Latency Analysis

## Claim Boundary

This analysis tests whether measured Spine time follows work that the
execution actually realizes. It does not substitute graph size or a fitted
edge-count formula for execution events. Every work quantity comes from the
frozen update artifact or a simulator counter. Every case must pass both
architecture-precision and independent mathematical correctness checks.

The output has two timing scopes:

- `exclusive_overlap_aware_critical_path` uses actual maintenance, reader, and
  compute start/end cycles. It emits maintenance, resolve-only, app-only,
  resolve/app-overlap, sync, and other time, and must sum exactly to E2E.
- `direct_execution_counters_nonexclusive_cycles` retains mechanism-local
  active or wait cycles for regressions. These values may overlap and must not
  be stacked as E2E time.

Independent PageRank runners currently expose an integrated iteration span,
not separate reader and app timestamps. Their critical-path remainder is
therefore labeled `integrated_resolve_app_cycles` and is excluded from the
fine-grained `M_phys` timing regression unless direct component timing exists.

## Counter Mapping

| Paper quantity | Direct simulator evidence |
|---|---|
| `W_sort(B)` | physical records in the frozen update artifact |
| `W_carry` | old payload reads + merge inputs + output rewrites; cursor bitmap bits are exported separately |
| directory requests | target-selector metadata reads plus family-directory reads |
| `M_phys` | processed physical edge records; exact range/fallback payloads are the fallback alias |
| `M_seed` | unique dirty sources emitted by maintenance |
| touched pages | carry pages visited and L0/carry bitmap page writes |
| descriptor operations | row, mask, page-base, page-list, and page-epoch writes |
| source services | reader source requests |
| reactivations | emitted next-frontier vertices |

The analyzer also exports a support flag for every regression. Missing timing
counters are excluded instead of being treated as zero work.

Representative stacked bars have a second admission gate. `zero_net` requires
an explicit zero-net mode or persisted-edge counter; a missing counter is not
interpreted as zero. `deep_carry` requires positive direct carry work, and a
PageRank correction requires thresholded residual PageRank with positive
physical edge work. Full PageRank is reported separately because it is a full
iteration, not an incremental correction.

## Formal Evidence

The 2026-07-30 formal snapshot contains 54 distinct correctness-gated Spine
executions after explicit plugin precedence removes repeated runs. It includes
three independently generated trace-history carry matrices (batch sizes 4, 8,
and 16), real-topology dynamic runs, and standalone zero-net and residual
correction cases. Twenty-four executions expose split physical-work timing.
The all-row OLS results are:

| Relationship | Samples | R2 | Interpretation |
|---|---:|---:|---|
| carry wait cycles vs. `W_carry` | 15 | 0.9995 | direct payload movement explains carry wait across levels and batch sizes |
| resolve + app active cycles vs. `M_phys` | 24 | 0.9933 | physical edge work explains the dominant split compute span |
| seed schedule cycles vs. `M_seed` | 39 | approximately 1.0000 | seed publication scales almost linearly in covered traces |
| sync cycles vs. source services + reactivations | 24 | 0.9915 | frontier service work explains inter-round synchronization |
| directory cycles vs. directory requests | 39 | 0.0011 | request count alone does not explain fixed and parallel directory timing |
| switch wait cycles vs. touched pages + descriptors | 39 | 0.0181 | this aggregate work count does not transfer across the mixed case classes |

The carry result is not an in-sample-only fit. Calibration uses eight cases
and obtains `R2=0.9986`; the seven holdout cases obtain `R2=0.9998`. The
trace-history setup reconstructs the exact level occupancy produced by
`2^L-1` chronological equal-size insertion batches, then times only the next
batch through the normal maintenance pipeline. It therefore exposes real
payload reads, merge input work, output writes, AXI waits, and FIFO effects.

All five requested representative classes pass the coverage gate: one
explicit zero-net case, 22 shallow insertions, 15 deep-carry cases, one
nonzero residual correction, and six deletion/weight-change fallbacks. Every
selected row has zero architecture-oracle and mathematical-oracle mismatch.
The representative ledger closes exactly to E2E cycles. The directory and
switch regressions above are negative findings: they need a richer predictor
before the paper may claim that those quantities explain timing.

## Reproduction

```bash
cd /home/chuxiao/spine-cycle-sim-publication
SPINE_RQ3_OUTPUT_DIR=/data/tmp/chuxiao/large_graph_campaign_v1/rq3_formal_analysis_v3 \
  bash scripts/analyze_active_rq3.sh
```

Trace-history carry evidence was generated with the immutable plugin
`/data/tmp/chuxiao/rq3-trace-carry-native-build-20260730/libspine_cycle.so`
(`sha256=65489ede127dc900e72603c3e6b0be89f1b362a6bf0ff6ef510b4de3f27b5254`):

```bash
python3 scripts/run_rq3_carry_trace_matrix.py \
  --out-dir /data/tmp/chuxiao/large_graph_campaign_v1/rq3_trace_carry_v1 \
  --lib-dir /data/tmp/chuxiao/rq3-trace-carry-native-build-20260730 \
  --batch-edges 8 --no-build
python3 scripts/run_rq3_carry_trace_matrix.py \
  --out-dir /data/tmp/chuxiao/large_graph_campaign_v1/rq3_trace_carry_calib_e4_v1 \
  --lib-dir /data/tmp/chuxiao/rq3-trace-carry-native-build-20260730 \
  --batch-edges 4 --role synthetic_calibration --no-build
python3 scripts/run_rq3_carry_trace_matrix.py \
  --out-dir /data/tmp/chuxiao/large_graph_campaign_v1/rq3_trace_carry_holdout_e16_v1 \
  --lib-dir /data/tmp/chuxiao/rq3-trace-carry-native-build-20260730 \
  --batch-edges 16 --role trace_holdout --no-build
```

Generated files:

```text
/data/tmp/chuxiao/large_graph_campaign_v1/rq3_formal_analysis_v3/rq3_summary.json
/data/tmp/chuxiao/large_graph_campaign_v1/rq3_formal_analysis_v3/rq3_work_rows.csv
/data/tmp/chuxiao/large_graph_campaign_v1/rq3_formal_analysis_v3/rq3_latency_rows.csv
/data/tmp/chuxiao/large_graph_campaign_v1/rq3_formal_analysis_v3/rq3_regression_rows.csv
/data/tmp/chuxiao/large_graph_campaign_v1/rq3_formal_analysis_v3/rq3_representative_rows.csv
/data/tmp/chuxiao/large_graph_campaign_v1/rq3_formal_analysis_v3/rq3_coverage_rows.csv
```

Verification:

```bash
python3 -m unittest -q tests.test_rq3_realized_work
python3 -m unittest discover -s tests -q
git diff --check
```
