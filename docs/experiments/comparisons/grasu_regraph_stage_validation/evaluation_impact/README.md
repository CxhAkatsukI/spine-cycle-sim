# Baseline Validation Before Spine Comparison

## Acceptance Order

1. **G versus original G:** identical prepared updates, initial PMA, physical
   operation count, segment geometry, memory/clock and event window. Check
   complete state and traffic first, then speed. Source-functional agreement
   alone is not timing agreement. Public source16 and paper8 are distinct.
2. **R versus original R:** keep original publication topology A separate
   from original four-Little A4. Compare the actual modified adapter/K4 path
   with A4 on common resident state and convergence semantics. Publish resource
   differences rather than calling four frontends equal resources.
3. **G + adapter/R:** validate the actual PMA handoff and non-overlapping event
   windows, including a separately measured host window. Separate-stage matches
   are necessary, not sufficient, for integration admission.
4. **Spine comparison:** only an admitted baseline may support an updated
   performance claim. Use identical warm state, logical batch, completion and
   setup policy. An exploratory diagnostic must not replace Figure 7.

The approximately 10% target is a declared test, not a fitting instruction.
Keep every mismatch, timeout and unsupported configuration. Never change
latency, credits or an upstream control to manufacture agreement. Original
paper reproduction additionally requires its actual workload and denominator;
same-source controls cannot silently stand in for that claim.

## Current Decisions

| Gate | Evidence now | Decision still open |
| --- | --- | --- |
| G, prepared PMA windows and complete shards | All 228 single-window observations pass. The 24-row synthetic whole-batch study passes; 36 additional compact AU/SU/WK observations exercise multi-segment searches and replay all 24 old rows exactly. Maximum new cycle differences are 0.897% for four banks and 2.367% for runtime mapping | Actual temporal operations, broader occupancy, HLS II/clock/resource fit, original-paper timing |
| R, fixed Amazon warm SSSP | All 12 full-convergence executions pass; candidate is 4.62% slower / 3.13% faster than A4 at latency 64 / 128 | A4 has 13 masters on 9 banks; K4 has 9 masters; 28 credit/window controls are queued with zero timing rows; broader inputs and original topology A remain separate |
| Physical G-to-R handoff | All 12 complete-cache executions pass high source IDs, hot/DDR edits, full preload/writeback and exact downstream convergence; 34 CTest targets, 228 old G rows and default SST regressions pass | Correctness alone cannot admit realistic batch performance; cache cost is paid once per updated shard |
| Host/seed and complete baseline | Device windows and excluded preparation are defined explicitly | Host/seed timing and complete baseline admission are not established |
| New Spine comparison | No replacement evaluation claimed | Requires the preceding gates and a common warm-state-to-convergence run |

These are simulator predictions and correctness checks, not new measured FPGA
speedups. The original G window is co-located; the newer whole-batch study
separately checks synthetic prepared shards and actual runtime mapping, with
complete cache cost. Its separate compact real-topology extension covers
multi-segment searches but still has cache-dominated timing and derived
updates, not actual temporal operations. The R case preloads
the post-update graph, old converged state and
prepared seed; it excludes G, DMA and host work on every arm. Separate passing
predictions cannot be added and called a validated complete-system result.

## Evidence Map

Read the [execution plan](PLAN.md) for acceptance order. Each guide below owns
its numerical findings, retained failures, resource assumptions, reproduction
commands and compact raw evidence. Earlier checkpoints keep their original
scope; they are not overwritten when a later candidate improves.

| Question | Guide |
| --- | --- |
| What failed in the first matched G/R diagnostic? | [Initial results](RESULTS.md), [frozen evidence index](evidence/index.json) |
| Did parallel search alone solve G? | [Parallel search](parallel_search/README.md), [hot owners](hot_lanes/README.md) |
| What did full caching and concurrency change? | [Complete cache](cached_hot/README.md), [search concurrency](search_concurrency/README.md) |
| Where was the remaining G delay? | [Read-only search diagnostics](search_diagnostics/README.md) |
| What buffers and finite timing does the close G prediction pay? | [Metadata credits](metadata_credits/README.md), [finite cycle model](search_pipeline/finite_model/README.md) |
| Does that G prediction hold across complete updated shards and runtime mapping? | [Prepared whole-batch study](sharded_batch/README.md), including complete cache cost, untouched state and retained preflight failures |
| Does G still match with real-topology, multi-segment searches? | [Compact AU/SU/WK controls](sharded_batch/real_inputs/README.md), all 36 observations plus exact 24-row regression; derived batches, not publication reproduction |
| Which HLS/source checks are independent of that prediction? | [Finite search HLS](search_pipeline/README.md), [cache probes](cache_probe/README.md), [weighted ABI](weighted_abi/README.md) |
| What differs between A4 and actual K4 resources? | [Resource audit](r_resources/README.md), [credit/window controls](r_credits/README.md) |
| Does R read the physical PMA produced by G? | [Direct handoff](composition/README.md), [finite bank routing](composition/banked/README.md), [complete-cache handoff](composition/cached/README.md) |

The original [matched-G](evidence/matched_g.json),
[R convergence](evidence/r_convergence.json) and
[failed first attempt](evidence/failed_attempt_v1.json) remain intact. The first
G timing gate failed; the subsequent finite candidate does not retroactively
make that implementation pass. The first R run exhausted its cycle budget
before convergence; its failure remains indexed, not silently dropped.

## Safety And Reproduction

The commands below reproduce the **initial diagnostic**, not the latest
complete-cache handoff. Use the individual study guides for current commands
and their stricter admission rules. For the initial diagnostic, use up to
four independent processes, with a 4-GiB per-process address-space
limit, a 24-GiB system reserve, bounded timeouts and an outer 8-GiB cgroup.
Parallel launch additionally requires memory for all process limits plus the
reserve; measured v1 peak was below 1 GiB for the complete service. Record compiler,
affinity, source/input/binary hashes, resource logs and all failures. Do not
start a second FPGA build or alter the queued route's pinned files.

```bash
python3 -m spine_cycle_sim.experiments.evaluation_impact.study \
  --output /path/to/fresh-output \
  --basis /path/to/model-bank-wide-v1 \
  --grasu-report results/upstream_stage_controls/grasu_finite_final_v1/run/report.json \
  --jobs 4 --maximum-cycles 1500000000 --case-timeout 1800

python3 -m spine_cycle_sim.experiments.evaluation_impact.common_g.study \
  --output /path/to/fresh-common-g-output \
  --core-build /path/to/fresh-output/build/simulator/cpp
```

Code ownership: `spine_cycle_sim/experiments/evaluation_impact/` for bounded
execution/analysis; `cpp/tests/evaluation_impact/` for the independent
convergence harness. Old handoffs and numerical evidence remain immutable.

Package a fresh evidence directory after both diagnostic reports complete:

```bash
python3 -m spine_cycle_sim.experiments.evaluation_impact.delivery \
  --output /path/to/fresh-evidence \
  --g /path/to/fresh-common-g-output/results.json \
  --r /path/to/fresh-output/results.json \
  --failed /path/to/retained-failed-attempt/results.json \
  --integration /path/to/grasu-regraph-integration \
  --hls-build /path/to/frozen-production-build

python3 -m unittest tests.test_evaluation_impact -v
```

The packager refuses running/incomplete reports or changed frozen files;
tests verify the committed capsule without requiring machine-local raw paths.
Raw graph/binary/log artifacts stay indexed outside Git. No production plugin,
paper source or figure handoff is changed by packaging.

## Figure Impact Rules

| Figure | Evidence | Consequence of adapter/R optimization alone |
| --- | --- | --- |
| 7 | Recorded FPGA measurements | Historical measurements remain valid for their bitstreams; a new baseline needs new matched hardware runs |
| 8 | Persistent update-only, host preparation included | Adapter/R propagation is outside the window; reassess if G/layout/preparation changes, not by dividing by the R speedup |
| 9 | Simulator accepted bytes and modeled HBM energy | R traffic must be rerun after promotion; energy needs the new timed request trace, not merely new cycle totals |
| 10 | Spine-only predicted normalized stage attribution | An R-only change does not alter Spine stage data; stage calibration remains unachieved |
| 11 | Spine-only realized-work fit to simulator cycles | An R-only change does not alter the fitted dataset; no new hardware-calibration claim follows |

Do not extrapolate the fixed Amazon compute speedup to all algorithms or
datasets, or multiply the old figures by a common factor. Until the G timing,
resource and integration gates close, this folder is diagnostic evidence,
not a validated replacement evaluation.
