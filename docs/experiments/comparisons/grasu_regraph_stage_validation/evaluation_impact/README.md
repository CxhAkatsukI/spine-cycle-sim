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

## This Checkpoint

The [resident G-to-R handoff](composition/README.md) adds an explicit,
default-off route that validates and reuses G's physical PMA rather than
rebuilding R input from logical edges. Its complete small matrix covers
updated and untouched shards, reserved slots, empty batches and registration
order; seven invalid handoffs must fail without repair. It uses unchanged
direct G, not the finite cached candidate. This is physical correctness,
not complete-G timing, seed/host admission or a new Spine performance claim.

The [finite G search cycle model](search_pipeline/finite_model/README.md)
now pays explicit registered arbitration, response routing, bounded reorder
holding and complete drain. All 228 executions pass state/work/traffic checks;
190 preceding observations replay exactly. Across every declared nonempty
input, finite G takes 0.9840--1.0455x the forwarded original at latency 64 and
0.9924--1.0217x at latency 128. The finite-stage prediction gate passes without
changing original timing or physical banks. Fresh core/SST default regressions
pass. The declared II=1/register assumptions still need HLS verification;
whole-G, original-publication, temporal/composition and production admission
remain open. No paper or frozen figure package changes.

The [R credit/window controls](r_credits/README.md) now predeclare 28
full-convergence executions to test the different A4/K4 outstanding budgets.
The pre-extraction source and twelve reference results are frozen. New arms
retain the old controls and explicitly vary parent credits or Apply window;
no strict resource match or numerical equivalence is claimed before replay.
The fresh Release build, eight C++ checks and 58 focused Python tests passed.
Timing execution has produced zero rows and waits for the existing memory
and competing-build reserves; the study guide links its persistent service
and retained raw logs.

The [R resource audit](r_resources/README.md) corrects a summary-table error:
original A4 has 13 distinct masters on 9 physical banks, while K4 registers
9 masters. It verifies constructed resources without executing a round or
changing model timing. Different credits, banks and replicas still prevent
strict resource-match admission for the preceding close R prediction.

The [finite search pipeline](search_pipeline/README.md) is the isolated HLS
feasibility follow-up: 64 ordered contexts, hierarchical arbitration, explicit
32-entry metadata FIFOs and bounded source backpressure controls. It does not
change the production core/SST or inherit the model's timing-retention result.
Its HLS/RTL job waits behind the cache comparison and reserves the pending
route's memory budget. The complete-G and publication gates remain open.

The [metadata-buffer controls](metadata_credits/README.md) retain the complete
diagnostic declaration and add 32/64-slot controls on the candidate's single
metadata master per CU. Physical banks, issue bandwidth, cache timing and all
other masters are unchanged. All 190 state/work/traffic observations pass;
114 preceding rows replay exactly. Both controls are within 2% of the
forwarded original over the complete nonempty matrix. This closes this
declared prediction-retention gate, not HLS feasibility, original-publication
timing, production baseline or composition admission.

The [read-only search/port diagnostics](search_diagnostics/README.md) exactly
replay 114 original/16-context/64-context observations across all nineteen
inputs and both memory assumptions. Large-batch differences precede cache
writeback, with the candidate's search ending later despite earlier preload.
Per-port credit observations motivate a separate resource-accounted control;
they are not proof that extra credits solve the gap or FPGA timing calibration.
Those diagnostics alone did not close the performance gate; the subsequent
metadata-buffer study supplies the separately resource-accounted control.

The [search-concurrency controls](search_concurrency/README.md) retain all
190 cached-G observations and add explicit 64-context and original same-row
forwarding arms. All 266 observations pass state/work/traffic checks and the
190 earlier rows reproduce exactly. Fresh checks pass 31 CTest targets,
92 focused Python tests and three default SST checks. Large 64K batches remain
52--55% slower than the forwarded original, so the complete performance gate
still fails. Default paths and production admission are unchanged.

The [explicit cached-G study](cached_hot/README.md) adds a separately owned,
default-off full-depth cache processor and a 190-observation matrix. It pays
complete preload/writeback and preserves every earlier control. Legacy
original-G same-row timing, integrated HLS and production/publication
admission remain separate open gates; model closeness does not close them.

The [weighted source compatibility check](weighted_abi/README.md) passes all
16 declared hot-region rows: actual host layout, original search, current
dispatch, original/candidate cache edits and actual adapter output. Complete
intermediate state and independent logical graph agree. This is not timing or
whole-G admission; all three earlier failed attempts remain in its capsule.

The [hot-cache HLS/RTL controls](cache_probe/README.md) test the original
full-depth URAM path and a separately registered lower-LUT candidate. Complete
cache state, finite FIFO correctness and estimated clock are separate gates;
neither the production G implementation nor simulator timing is changed by
these component probes. Full G and publication admission remain open.

The preceding [hot-owner G checkpoint](hot_lanes/README.md) extends the study to
152 observations with explicit segment-ordered parallel RMW and unchanged
physical traffic. It reproduces the old 84 observations exactly, but the
complete performance gate still fails on large batches and same-key hazards.
It is not a production HLS change or a new Spine/G+R comparison.

The subsequent [parallel-search G checkpoint](parallel_search/README.md)
retains a complete 84-run three-arm matrix and two isolated HLS attempts.
It improves search throughput but fails the large-batch performance gate and
the 200-MHz HLS clock estimate. It is not a promoted baseline or a replacement
for the immutable evidence below.

Read the [execution plan](PLAN.md) and [diagnostic findings](RESULTS.md).
The [evidence index](evidence/index.json) owns report identities and admission
flags. It contains the [matched-G report](evidence/matched_g.json),
[complete R report](evidence/r_convergence.json) and
[failed first attempt](evidence/failed_attempt_v1.json), not just passing rows.
This study first replays all twelve finite-G configurations against original
source16 probes and frozen observations. That is an exact regression check,
not a current-G timing comparison or a measurement of FPGA cycles from C++
source-probe wall time.

A separate matched-input G diagnostic then runs unchanged
`GraSuPmaUpdateSystem` and the independent `original_grasu` model on the same
prepared PMA and updates. All twelve runs pass state/traffic gates, but
nonempty batches do **not** meet the declared performance-retention target.
It covers a single destination window, not the complete 23-channel sharded G
system. Original-G publication/FPGA timing admission remains open as well.

The R diagnostic extends the fixed Amazon warm-update case from one round to
convergence for original A4, unchanged cross-row K4 and the bank-stream
candidate. It checks each A4 round, all final state words/replicas, active-count
trajectories, independent shortest-path closure and physical request ledgers.
It is a compute-only prediction: the graph after three source-0 weight
decreases and the old resident state are preloaded. G, seed preparation,
DMA/launch and host orchestration are excluded on all arms. It is **not** a
complete Spine/G+R E2E demonstration.

All twelve R executions now pass. The candidate is 4.62% slower / 3.13%
faster than A4 at latency 64 / 128, respectively, over 46 rounds to convergence.
That meets the declared prediction target on this case; resource differences
and unadmitted publication/FPGA timing prevent a general baseline claim.

Predeclared R matrix: latencies 64 and 128, both registration orders, all
three arms, maximum 128 rounds / 1.5 billion cycles per arm. Attempt v1 reached
the earlier 200-million-cycle budget during cross-row round 38, before the
46-round oracle closure. Its failure is retained. Attempt v2 changes only the
execution budget (1800 seconds per case) and parallelism, not model timing.
Resources and
numerical components are unchanged from the fixed one-round study. The
candidate uses 1024-row tiles, two 256-line banks and progressive AXI beats.
Neither the production SST plugin nor existing bitstreams are replaced.

## Safety And Reproduction

Use up to four independent processes, with a 4-GiB per-process address-space
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
