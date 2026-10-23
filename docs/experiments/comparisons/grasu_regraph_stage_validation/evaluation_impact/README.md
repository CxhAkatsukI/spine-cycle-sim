# Baseline Validation Before Spine Comparison

Current priority is **simulator only**. FPGA compilation, routing and board
tests are deferred, not prerequisites for the next prediction diagnostics.
They remain necessary for any eventual new measured-hardware claim.

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

On 2026-10-23 the user authorized an
[exploratory common-warm Spine diagnostic](warm_comparison/README.md)
before complete admission. This preserves the outstanding gates and reports
device-cycle predictions, including failures, rather than replacing Figure 7.

The latest [current-input isolation](r_bank_stream/prefetch_compact/INPUT_ISOLATION.md)
passes sixteen diagnostic executions, eight exact historical replays and
physical-byte conservation. High-latency input service remains restricted;
this is not a complete-R admission. The latest complete
[Gather reuse control](r_bank_stream/prefetch_compact/GATHER_REUSE.md) now
takes 0.953364 / 1.157245 times A4 with unchanged traffic: only latency 64
meets the declared 10% band. This is still an experimental prediction,
not production admission, and no FPGA work is required for these diagnostics.

## Current Decisions

| Gate | Evidence now | Decision still open |
| --- | --- | --- |
| G, prepared PMA windows and complete shards | One-shard chronological runtime fails all six 64K comparisons (22.7--35.5% slower); both-table copies reduce maximum difference to 4.3618%. The new resident AU/SU/WK check passes 18 executions/54 batches; both-copy maximum difference is 0.7432%, while shared last batches still fail. Both extractions preserve the preceding 12-row lifecycle matrix exactly | Routed 64K-partition geometry, changed-reservation refresh, measured host costs, original temporal conversion, mixed hot/cold occupancy, actual HLS binding/II/clock/resource fit, original-paper timing |
| R, fixed Amazon warm SSSP | Default current/A4 remains 2.951 / 3.635 at latency 64/128. The latest source-backed Gather reuse control passes twelve complete executions, exact eight-row old replay, 144 finite-input executions and a fresh 37/37 numerical-core suite. It takes 0.953364 / 1.157245 times A4, reducing complete cycles by 12.11% / 6.94% from the wrapper control without changing traffic | Only latency 64 passes the 10% gate; overall retention still fails and the candidate stays default-off. A4 has 13 masters/four state replicas versus candidate 16/three, not strict resource equality. Remaining input/service restrictions, broader inputs, host costs and original-publication matching remain open; do not adjust timing to fit |
| Physical G-to-R handoff | All 12 complete-cache executions pass high source IDs, hot/DDR edits, full preload/writeback and exact downstream convergence; 34 CTest targets, 228 old G rows and default SST regressions pass | Correctness alone cannot admit realistic batch performance; cache cost is paid once per updated shard |
| Host/seed and complete baseline | Device windows and exclusions are explicit; the common-warm demo's partial CPU preparation is now measured (Amazon Spine 0.0891 us, G 0.3183 us) and does not change its direction | Active-state application, DMA, launch/relaunch, readback and complete host-inclusive timing remain unestablished; no baseline admission |
| Exploratory Spine comparison | Complete 12-execution common-warm diagnostic: Amazon three-insertion SSSP gives 5.3226 / 5.2749 times G+R/Spine at latency 64/128; the small latency-128 smoke instead gives 0.7224. Eight same-batch A4 executions now pass full-state/order/ledger gates; Amazon R/A4 is 1.017585 / 1.199468, smoke approximately 1.480 | Device-only, one real slice/two-round propagation; only one of four same-batch conditions is within 15%. Broader algorithms/batches, resource equality and host-inclusive comparison remain open. No replacement evaluation claimed |

These are simulator predictions and correctness checks, not new measured FPGA
speedups. The original G window is co-located; the newer whole-batch study
separately checks synthetic prepared shards and actual runtime mapping, with
complete cache cost. Its separate compact real-topology extension covers
multi-segment searches but still has cache-dominated timing and derived
updates. The newer chronological first-contact study retains actual timestamp
order with explicit insertion-only conversion and exposes a larger-batch
runtime mismatch; it does not recover original GraSU temporal semantics.
Copy controls now support a shared-metadata contention explanation, but
their extra storage and excluded replica preparation prevent production
or host-inclusive admission from that result alone.
The synthetic resident extension verifies fixed-reservation replica coherence;
the newer chronological extension checks 4K/empty/61,440-insertion sequences
across two or three shards. Both-copy predictions pass, but all edited segments
remain hot, reservations use the future union, and partition width is 8K
rather than the routed 64K. Neither checks arbitrary metadata changes or
admits production performance. Initialization ledgers are bytes, not measured
CPU/DMA time.
The R case preloads
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
| Does improved R erase Spine's advantage in a first common-warm diagnostic? | [Exploratory Spine comparison](warm_comparison/README.md), twelve complete SSSP executions with real physical G-to-R handoff, approximately 5.3-times advantage on one real slice and a retained negative smoke; device prediction only |
| Does that exact insertion batch retain original A4 performance? | [Same-batch A4 follow-up](warm_comparison/SAME_BATCH_A4.md), eight executions and portable full-state/raw evidence; Amazon +1.76% / +19.95%, smoke approximately +48%. Across-scenario parity is not established |
| Does measured warm-batch CPU preparation change the demo's direction? | [Partial host audit](warm_comparison/HOST_PREPARATION.md), fourteen fresh process repetitions plus retained pilot; small-batch sorting/packing is negligible here, but full host-inclusive time remains unknown |
| Does the current two-pair bank-stream R retain A4 compute performance? | [Current bank-stream convergence controls](r_bank_stream/README.md), completed 32-row matrix, exact 28-row replay and retained approximately 3-times mismatch |
| Does finite prefetch and padding compaction recover complete R performance? | [Compact-input convergence](r_bank_stream/prefetch_compact/CONVERGENCE.md), default-off input owner, full-state and legacy replay gates; retention has not passed |
| Which waits remain after compaction? | [Passive R observations](r_bank_stream/prefetch_compact/OBSERVATIONS.md), exact twelve-row replay, order-independent overlapping counters and candidate next steps; no timing change |
| Does independent source loading recover the R gap? | [Finite source-cache schedule](r_bank_stream/prefetch_compact/SOURCE_LOADING.md), sixteen full-convergence rows, exact twelve-row replay and fresh compatibility; 2.519 / 2.150 times A4, so retention still fails |
| Can explicit extra reader masters relieve the unchanged PMA scan? | [Reader-port diagnostic](r_bank_stream/prefetch_compact/READER_PORTS.md), eight correct rows, four exact old replays and conserved physical input; 31.15% faster at latency 64 but 4.70% slower at 128, with both reader floors still above the retention gate; not an integrated R performance claim |
| Do full bursts recover the remaining reader gap? | [Full-burst refill](r_bank_stream/prefetch_compact/BURST_REFILL.md), sixteen correct reader rows, eight exact eager replays and unchanged physical traffic; dual-port cycles improve 0.43% at latency 64 but regress 2.40% at 128. The hypothesis fails; no new complete-R or Spine result |
| Does a third finite pipeline slot plus dual readers recover complete R? | [Explicit elastic-pipeline candidate](r_bank_stream/prefetch_compact/ELASTIC_PIPELINE.md), twelve correct complete executions and eight exact old replays; 1.787 / 2.209 times A4 with the latency-128 regression retained. Retention fails; no new Spine comparison |
| Does a separate physical directory master recover the remaining R gap? | [Metadata-port candidate](r_bank_stream/prefetch_compact/METADATA_PORTS.md), twelve correct complete executions, eight exact old replays and unchanged traffic; 1.598 / 1.937 times A4 with 15 versus 13 masters. Both retention gates fail; input improves but ordered output/shared Apply remain diagnostic targets |
| Does separating Apply read/write masters close the R gap? | [Apply-port candidate](r_bank_stream/prefetch_compact/APPLY_PORTS.md), twelve correct complete executions, eight exact old replays and unchanged traffic; 1.555 / 1.554 times A4 with 16 versus 13 masters. Both retention gates fail; shared Apply explains part of the high-latency restriction, not the complete gap |
| Does finite directory lookahead close the remaining R gap? | [Two-tile directory candidate](r_bank_stream/prefetch_compact/DIRECTORY_OVERLAP.md), twelve correct complete executions, eight exact old replays and unchanged traffic; 1.479 / 1.552 times A4. Both retention gates fail; directory overlap alone is insufficient |
| Does finite ready-burst output close the remaining R gap? | [Addressed ready-burst candidate](r_bank_stream/prefetch_compact/READY_BURSTS.md), twelve correct complete executions, eight exact old replays and unchanged traffic; 1.0875 / 1.2474 times A4. Only latency 64 passes, so overall retention remains unachieved |
| Does increasing finite PMA storage close the remaining R gap? | [512-line ring candidate](r_bank_stream/prefetch_compact/PREFETCH_CAPACITY.md), twelve correct complete executions, eight exact old replays and unchanged traffic; 1.08514 / 1.24316 times A4. Less than 0.34% improvement despite 128 KiB added storage; overall retention fails |
| Does correcting the SSSP post-response interval close the gap? | [Apply schedule control](r_bank_stream/prefetch_compact/APPLY_SCHEDULE.md), twelve correct complete executions and eight exact old replays; 1.084725 / 1.243611 times A4. Source-backed interval correction changes complete time by less than 0.04%; overall retention still fails |
| Does correcting the wrapper pre-write interval close the gap? | [Wrapper schedule control](r_bank_stream/prefetch_compact/WRAPPER_SCHEDULE.md), twelve correct complete executions and eight exact old replays; all complete cycles equal the preceding Apply control. Both physical writes/responses remain; overall retention still fails |
| Can the latest reader alone approach the high-latency A4 window? | [Current-input isolation](r_bank_stream/prefetch_compact/INPUT_ISOLATION.md), sixteen executions and eight exact replays; finite fast-sink scans expose a credit/placement restriction without replacing complete-R time |
| Does eliminating redundant Gather initialization close the gap? | [Destructive Gather reuse](r_bank_stream/prefetch_compact/GATHER_REUSE.md), twelve correct complete executions, eight exact old replays and fresh 37-target core regression; 0.953364 / 1.157245 times A4 with unchanged physical traffic. Only latency 64 passes, so overall retention still fails |
| What is the current hardware execution and acceptance order? | [Hardware validation campaign](hardware_validation/README.md), separate component, routed, publication and complete-system gates |
| What failed in the first matched G/R diagnostic? | [Initial results](RESULTS.md), [frozen evidence index](evidence/index.json) |
| Did parallel search alone solve G? | [Parallel search](parallel_search/README.md), [hot owners](hot_lanes/README.md) |
| What did full caching and concurrency change? | [Complete cache](cached_hot/README.md), [search concurrency](search_concurrency/README.md) |
| Where was the remaining G delay? | [Read-only search diagnostics](search_diagnostics/README.md) |
| What buffers and finite timing does the close G prediction pay? | [Metadata credits](metadata_credits/README.md), [finite cycle model](search_pipeline/finite_model/README.md) |
| Does that G prediction hold across complete updated shards and runtime mapping? | [Prepared whole-batch study](sharded_batch/README.md), including complete cache cost, untouched state and retained preflight failures |
| Does G still match with real-topology, multi-segment searches? | [Compact AU/SU/WK controls](sharded_batch/real_inputs/README.md), all 36 observations plus exact 24-row regression; derived batches, not publication reproduction |
| Does that extend to larger timestamp-ordered batches? | [Chronological first-contact diagnostic](sharded_batch/chronological_inputs/README.md), all 36 new rows and exact old replay; four-bank passes, 64K runtime fails |
| Can metadata placement explain the larger-batch runtime gap? | [Metadata layout controls](sharded_batch/metadata_layout/README.md), 72 rows, exact old replay and explicit copy costs; both-copy prediction passes, production admission remains open |
| Do copies remain coherent across resident batches and shards? | [Resident lifecycle](sharded_batch/metadata_layout/lifecycle/README.md), 12 executions and exact 72-row regression; fixed reservations, explicit initialization costs and separate HLS connectivity audit |
| Does that hold for larger resident chronological batches? | [Resident AU/SU/WK](sharded_batch/metadata_layout/resident_real/README.md), 18 executions/54 batches, all copy predictions within 0.7432%, retained shared failures and exact lifecycle replay; bounded 8K partitions, not production admission |
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
affinity, source/input/binary hashes, resource logs and all failures. The
original diagnostic serialized FPGA builds. The current
[hardware campaign](hardware_validation/README.md) instead permits bounded
concurrent tools when all hard budgets plus the system reserve fit. Never
alter a running attempt's pinned files.

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
