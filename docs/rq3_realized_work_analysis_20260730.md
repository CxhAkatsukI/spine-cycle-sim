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
| `W_carry` | carry cursor edge bits inspected plus new-batch carry reads |
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

## Current Provisional Evidence

The 2026-07-30 live snapshot contains 35 distinct Spine executions after
explicit plugin precedence removes repeated v3/v4/v5/v6 runs. Twenty-two have
complete split reader/compute timing. The current all-row OLS results are:

| Relationship | Samples | R2 | Interpretation |
|---|---:|---:|---|
| resolve + app active cycles vs. `M_phys` | 22 | 0.993 | physical edge work explains the dominant split compute span |
| seed schedule cycles vs. `M_seed` | 22 | approximately 1.000 | seed publication scales almost linearly in covered traces |
| switch wait cycles vs. touched pages + descriptors | 22 | 0.992 | page/descriptor work explains switch wait in covered traces |
| sync cycles vs. source services + reactivations | 22 | 0.991 | frontier service work explains inter-round synchronization |
| directory cycles vs. directory requests | 22 | 0.163 | request count alone does not explain fixed/parallel directory timing |

No covered formal trace performs deep carry, so `W_carry` has no variance and
no slope or R2 is reported. A deep-carry calibration set and separate real
trace holdout are required before making the carry claim. These numbers are
provisional until the v6 large-graph campaign and the five requested RQ3 case
classes are complete.

The analyzer writes a machine-readable coverage gate. At the current live
snapshot, shallow insertion and deletion fallback are ready; explicit
zero-net, deep carry, and nonzero residual correction remain missing. Missing
classes are omitted from representative bars rather than replaced by a
different mechanism.

## Reproduction

```bash
cd /home/chuxiao/spine-cycle-sim-publication
bash scripts/analyze_active_rq3.sh
```

Generated files:

```text
/data/tmp/chuxiao/large_graph_campaign_v1/rq3_live/rq3_summary.json
/data/tmp/chuxiao/large_graph_campaign_v1/rq3_live/rq3_work_rows.csv
/data/tmp/chuxiao/large_graph_campaign_v1/rq3_live/rq3_latency_rows.csv
/data/tmp/chuxiao/large_graph_campaign_v1/rq3_live/rq3_regression_rows.csv
/data/tmp/chuxiao/large_graph_campaign_v1/rq3_live/rq3_representative_rows.csv
/data/tmp/chuxiao/large_graph_campaign_v1/rq3_live/rq3_coverage_rows.csv
```

Verification:

```bash
python3 -m unittest -q tests.test_rq3_realized_work
python3 -m unittest discover -s tests -q
git diff --check
```
