# Baseline Admission Plan

## Objective

Current execution scope: **simulator only**, per the user's 2026-10-22
instruction. Defer new FPGA compilation, routing and board experiments;
historical hardware gates below describe remaining evidence, not prerequisites
for running the bounded simulator comparisons. A simulator demo must retain
its prediction label even when hardware gates are deferred.

Establish that the implemented GraSU update path and ReGraph computation path
retain defensible performance relative to their independent originals before
using their composition as a baseline against Spine. A requested 10% match is
a testable outcome, not a promise or a tuning objective. A failed row is a
finding to explain and fix, never a reason to modify a timing coefficient.

Two distinct claims need separate decisions:

- **Implementation retention:** same-input, common-memory comparisons against
  independent source-derived original models, with explicit resource changes.
- **Published-performance reproduction:** original paper workload, topology,
  clock, device/memory, numerator and event window, plus an admitted timing
  model or original FPGA measurement. The first does not establish the second.

## Phase 1: Freeze And Inspect

Status: implemented for the bounded diagnostics.

Pin component source, unchanged SST plugin, initial graph/state, update batch,
compiled binary, compiler/flags, clocks, memory issue/credit/latency settings,
event windows and resource ledgers. Keep A (original mixed ReGraph), A4
(original four Little), B (actual adapter plus modified K4), and complete G+R
as distinct identities. The queued adapter-only route is not a G correction.

The production G build logs confirm `GRASU_COMPACT_HBM_PORTS` and
`GRASU_PURE_PIPELINE_DIRECT_CACHE`. These select sequential direct search and
direct HBM hot updates instead of the original parallel search/URAM path.
This is a real hardware-port difference, not only a plotting problem.

## Phase 2: Validate G Separately

Status: source/finite replay passed; the direct-HBM performance gate failed.
An explicit [cached-G candidate](cached_hot/README.md) now has a separate
finite processor and completed 190-observation matrix. State/work/traffic pass,
all 152 old observations are exact, and 30 fresh CTest targets pass. Large
cached batches remain 60--65% slower than the legacy original, so the 10%
retention gate still fails. Production baseline admission remains open,
including reference same-row timing and integrated HLS.

The separate [search-concurrency controls](search_concurrency/README.md) now
test source-grounded reference forwarding and 64 candidate contexts without
adding ports or credits. All 31 fresh core tests pass; all 266 observations
pass state/work/traffic checks and reproduce the complete 190-row checkpoint.
The large 64K cases still take 52--55% more cycles than the forwarded original.
The complete performance gate fails. Next isolate port/queue contention and
stage overlap before choosing a resource-accounted correction; do not infer
its cause solely from the different master counts. Production admission
remains open, separately from these prediction and regression checks.

The [read-only progress/port study](search_diagnostics/README.md) now replays
all 114 selected original/16-context/64-context rows exactly across the full
nineteen-input declaration and both latencies. Search ends late while cache
preload ends earlier; the final writeback tail matches the original. The
candidate's single metadata master is often credit-limited. Next test explicit
metadata-parent/burst/FIFO budgets without changing physical banks or timing,
retaining old arms and recording added buffering resources. Pressure alone
does not prove a fix or authorize production/FPGA admission.

The [metadata-buffer study](metadata_credits/README.md) implements that
separate control: the full nineteen-input, two-latency declaration retains
all 114 diagnostic rows and adds 76 observations with explicit 32/64-slot
metadata buffers. Default configuration, physical-bank capacity and unrelated
masters are unchanged. All 190 observations now pass state/work/traffic and
the old 114 rows replay exactly. Both new controls stay within 2% of the
forwarded original on every nonempty declared input. M32 suffices for this
prediction target; M64 remains a sensitivity control. This closes the declared
single-window prediction gate, not HLS feasibility. Next verify integrated
search/cache schedules, finite buffers and whole-G resource/clock fit, then
actual temporal inputs and composition. Production, publication and integration
decisions remain separately required.

The [finite search pipeline](search_pipeline/README.md) now gives that next
HLS check a separate implementation owner: 64 contexts with hierarchical
arbitration and explicit 32-entry metadata buffering. The full nineteen-input
declaration is exercised with and without bounded output stalls. Its isolated
synthesis/RTL attempt is queued behind the complete-cache check and preserves
the pending route's memory reservation. At that HLS checkpoint the new
arbitration-stage latency was not mirrored in the cycle engine. The subsequent
[finite cycle-model study](search_pipeline/finite_model/README.md) explicitly
models those stages with bounded queues, ordered responses and complete drain.
All 228 observations pass with exact replay of the preceding 190; all 38 new
observations preserve state/work/traffic and fit the declared +/-10% prediction
band. Worst slowdown versus forwarded original is 4.55% at latency 64 and
2.17% at latency 128. The fresh 31-target core suite and default SST regressions
pass. Its one-register, II=1 assumptions still require schedule verification;
prediction retention and source/work parity cannot close clock, publication
or integrated-G gates. The isolated worktree preserves queued-job source pins.

The [cache component controls](cache_probe/README.md) now examine original
URAM behavior rather than making cached timing an assumption. Original
single-bank and complete 16-bank C/RTL state checks pass; lower-LUT static
wiring has a separately checked registered option. This does not close whole-G
search timing, weighted ABI, two-half resource fit, or production admission.
The probes also expose conservative same-row serialization in the independent
reference model; any timing correction must preserve old evidence explicitly.
The [weighted source compatibility check](weighted_abi/README.md) now passes
16 hot-region rows across original/candidate cache edits and both adapter
modes. It checks original search, current dispatch, complete intermediate PMA
and emitted logical graph, not finite timing, cold edits or whole-G synthesis.
The fresh complete-cache comparison is queued behind unchanged memory limits;
its `WAITING_FOR_MEMORY` state does not close any performance or RTL gate.

The [prepared whole-batch G study](sharded_batch/README.md) now adds 24
observations covering one, three and five updated destination shards,
hot/DDR edits, an empty control, both latencies, four-bank controls and the
actual 23-channel runtime map. All complete state/work/traffic checks pass;
maximum absolute cycle differences from the prepared-shard original are
0.342% (four banks) and 0.173% (runtime mapping). Full preload/writeback is
paid once per touched shard. Fixed cache cost dominates these small batches,
and updated rows have no binary probes: real temporal input and multi-segment
whole-batch performance still need separate validation. Candidate HLS,
hardware and publication admission remain open. The adapter route's prior
24-hour memory queue expired before starting; its 64-GiB safety gate is not
lowered by this small simulator study.

The [compact real-topology extension](sharded_batch/real_inputs/README.md)
adds 36 AU/SU/WK observations with nonzero multi-segment binary searches,
unchanged frozen mixed/weight-change batches and exact replay of all 24
synthetic rows. Complete physical state, work and traffic pass; maximum
cycle differences are 0.8971% for four banks and 2.3669% for runtime mapping.
Both prediction gates pass. IDs are compact, edits are derived and all edited
segments are hot; cache cost still dominates. This closes this declared
real-topology prediction diagnostic, not actual-temporal, broader-occupancy,
host, HLS, hardware or publication gates.

The next [chronological first-contact diagnostic](sharded_batch/chronological_inputs/README.md)
adds 36 AU/SU/WK rows at 4K/64K insertions, with actual timestamp order and
explicit loop/repeat filtering, compact IDs and trace-aware all-hot reservation.
State/work/traffic pass; all 36 preceding real-topology observations replay
exactly both before and after an experiment-only order-preserving reader fix.
Four-bank maximum cycle difference is 4.71%, but runtime is 22.7--35.5% slower
on all six 64K comparisons and fails its declared gate. The initial sorted-input
rejection and zero numerical observations are retained. Next isolate shared
row/binary bank pressure and search progress with explicit resource controls;
do not promote the candidate or interpret small-batch success as general
admission. Original temporal conversion, mixed occupancy, host costs and HLS
feasibility remain separate gates.

The [metadata-placement diagnostic](sharded_batch/metadata_layout/README.md)
now runs 72 observations, replaying the old 36 exactly and retaining every
state/work/traffic check. Row-only or binary-only copies fail the complete
prediction gate; both-table copies pass with maximum absolute difference
4.3618%. Added storage is 8.30--8.61 MiB, and used channels increase from
10 to 13. This supports metadata-bank contention without changing a timing
parameter. The original runtime still fails. Next implement and verify an
explicit multi-shard correction, replica coherence and host costs with legal
HLS connectivity; immutable one-shard controls cannot promote themselves
to the production baseline or close hardware/publication gates.

The [resident lifecycle extension](sharded_batch/metadata_layout/lifecycle/README.md)
now checks fixed-reservation coherence with three shards and three consecutive
batches on one runtime backend. All 12 executions and 36 batch observations
pass full payload, untouched-copy and traffic checks; every preceding
metadata-layout observation and full-state hash replays exactly (72 rows).
Replica storage and logical initialization upload are explicit. Legal routed
SSSP port ranges are checked read-only; the actual host still binds shared
tables. Next validate larger multi-shard batches, changed-reservation refresh
and measured host preparation, then implement actual HLS binding with verified
search/cache schedules and whole-G fit. Small cache-dominated batches and
fixed-table consistency do not close those admission gates.

The [resident chronological check](sharded_batch/metadata_layout/resident_real/README.md)
extends that diagnostic to all three AU/SU/WK prefixes, 4K/empty/61,440 updates,
and two or three 8K-vertex shards. All 18 executions/54 batch observations pass
state/work/traffic/resource checks. Both copies keep every nonempty-batch
prediction within 0.7432% of original; shared last batches remain 10.2--12.8%
slower despite passing sequence totals. Both shared-helper extractions replay
the preceding 12 lifecycle observations and all batch hashes exactly. The
retained SU validator failure is explained with paired same-layout checks,
not erased or fixed with a timing factor. Next close changed-reservation,
mixed-occupancy, host and HLS gates; future-union all-hot 8K diagnostics do
not admit routed 64K performance or original-publication reproduction.

The preceding [hot-owner checkpoint](hot_lanes/README.md) retains all earlier
observations and extends to 152 four-arm runs. Sixteen segment-ordered owners
share each unchanged hot AXI master, with no implicit cache. Large dispersed
batches improve further but remain 17--23% slower than original G; large
same-segment batches are 7.4--7.8x slower. State/work/traffic and all 84 old
observations agree exactly. No hot-owner HLS timing or production baseline
admission follows from this default-off single-window prediction.

The [parallel-search checkpoint](parallel_search/README.md) now tests an
explicit default-off core candidate on 84 runs. It preserves state/work and
improves larger-batch predictions by about 5x, but the 16K/64K cases still miss
the original-G retention target. Two isolated HLS compiles also miss the
200-MHz estimated clock. The hot-owner model investigates update concurrency;
its HLS implementation, caching/forwarding costs and search arbiter timing
remain open, not admitted baseline changes.

The first common-input diagnostic covers batch sizes 0, 64 and 4096, both
64/128-cycle memory assumptions, identical prepared full-word PMA and updates,
200 MHz, four physical banks and resident update-to-drain windows. Complete
state, physical traffic and hot/cold routing are checked. Empty input is a
fixed-overhead control, never an updates-per-second data point.

Required next implementation work:

1. Keep the current direct path as a frozen control. Test original parallel
   search and hot-cache behavior with the same local-destination/weighted ABI;
   weight packing must not silently change search order or delete semantics.
   The hot source-functional subset now passes; full parallel-search control,
   cold paths, finite schedules and integrated hardware remain open.
2. Choose an actual HLS resource-feasible G path: restore the original cached
   path, or implement bounded parallel HBM search/update with RAW conflict
   handling. Confirm storage/ports, schedules and completion tokens. Do not
   silently model URAM that the hardware does not contain.
3. Mirror that chosen path in a separate reviewable simulator component;
   compare source/RTL state, requests, backpressure and timing assumptions.
   Rebuild core/SST in fresh directories and retain all old pins.
4. Rerun common inputs, larger/neighboring batches and hot/cold/conflicting
   keys, plus actual temporal workloads. Report both faster and slower rows.
   Thresholds apply to the complete declared nonempty matrix.
5. Admit original timing from published or board evidence separately. The
   reachable source16 configuration is not the paper's eight-slot geometry;
   the missing temporal conversion/denominator cannot be fitted away.

Exit: per-input state/work parity, documented resources and event window,
then a passing performance-retention decision. Failure retains the gate open.

## Phase 3: Validate R Separately

Status: correctness passes, but the current path fails the 10% retention
target against the stronger A4-io16 control. The completed 32-row local matrix
replays all 28 preceding observations exactly. Current bank stream is
2.951 / 3.635 times slower at 64/128-cycle memory latency. The initial
twelve-row match used weaker legacy A4 limits and is not baseline admission.
Broader workload, resource and publication timing admission remains open.

Run original A4, unchanged cross-row K4 and bank-stream candidate on the fixed
Amazon real-ID slice: old converged SSSP state, three source-0 weight decreases,
same post-update graph, propagation to zero active vertices. Check the
synchronous per-round oracle, independent shortest-path closure, final
replicas, active trajectory, traffic and request conservation. Predeclare
64/128-cycle assumptions and both registration orders; retain all 12 rows.

Then add neighboring graph/degree/occupancy cases and supported CC/ResPR
semantics before generalizing. Original ReGraph's published PR/BFS/Closeness
Centrality are not all identical to our algorithms. In particular, original
PR fixed sweeps cannot be compared to residual PR convergence as the same work.

List masters, physical banks, outstanding parents, state replicas, buffers,
merge/apply widths and clock: A4 and K4 are not strictly resource-identical.
The [credit/window sensitivity study](r_credits/README.md) retains all three
legacy arms and adds four explicit controls over both latencies and
registration orders. Its 28-row matrix requires exact replay of the twelve
old rows before interpreting new ratios. The completed credit study reports
2.949/3.635 candidate/A4-io16 at
64/128-cycle latency, so the old candidate does not pass retention against
that control. Equal credits do not equalize banks, replicas or source buffering.
The separate [current bank-stream study](r_bank_stream/README.md) adds the
seven-master production profile and requires exact replay of all 28 prior
rows before accepting its four new observations. That gate is complete in
the 2026-10-22 local CPU-only run; the remote final result remains unavailable.
Strict local admission denial and the first CPU-only regression timeout are
retained separately. The read-only frontend/Apply/writeback export now replays
all four current rows exactly; final drain is below 0.1%. Frontend and backend
waits still overlap, so endpoints are not additive stage or causal stall costs.
The [finite input studies](r_bank_stream/prefetch_compact/README.md) now test
compaction, explicit source loading, reader/directory ports, finite elastic
queues and separate Apply masters as named default-off architectures. Old
arms retain their original resources, traffic and timing. Their successive
complete predictions reduce the gap without yet meeting retention.
The [two-tile directory study](r_bank_stream/prefetch_compact/DIRECTORY_OVERLAP.md)
passes all twelve complete executions, exact eight-row replay, 36 fresh CTest
targets and 128 finite-input executions. It takes 1.479 / 1.552 times A4 at
latency 64/128; both retention gates fail. Its added 32 KiB of directory values
and 16-versus-13 physical masters are explicit resource differences.

The [ready-burst protocol](r_bank_stream/prefetch_compact/READY_BURSTS.md)
now passes twelve complete executions, eight exact old replays, 37 fresh
CTest targets and 128 finite-input executions. It preserves physical traffic
and complete state, improving 26.47% / 19.65% from directory lookahead.
Ratios are 1.0875 / 1.2474 times A4: only latency 64 passes the 10% gate,
so overall retention still fails. It remains default-off.

The [whole-parent refill study](r_bank_stream/prefetch_compact/READY_FULLBURST.md)
now completes all twelve executions and eight exact old replays on the same
topology, rings, masters, credits, traffic and memory service. Ratios remain
1.08734 / 1.24729 times A4; reductions below 0.015% do not close the complete
retention gate. Both live-memory safe aborts and verified same-binary recovery
are retained. Next distinguish finite prefetch lookahead/storage from
downstream waits; additional buffer capacity needs an explicit resource
control, not a faster latency coefficient. Input endpoints remain observations
under downstream backpressure, not additive stage times or intrinsic floors.
Broader workloads and G/host/composition gates remain open.
No FPGA build or board test is launched in this phase.
Compare A with A4 separately; never pretend four Little reproduces 11+3.
Use an admitted publication case to test the original R model's timing,
independently of the A4/B retention control.

Exit: no hidden resource/work advantage and passing retention on the declared
matrix. Simulation-only closeness remains prediction evidence until timing
admission. R success cannot compensate for failed G.

## Phase 4: Compose The Baseline

Status: not admitted; do not bypass the G/R gates.

The direct and finite-bank-routing physical handoffs now pass their declared
correctness matrices. The [complete-cache sharded matrix](composition/cached/README.md)
adds high source IDs, hot/DDR operations and full preload/writeback accounting.
These are integration checks, not admission of realistic batch performance,
host/seed timing or a new Spine comparison.

Feed G-produced PMA directly into the actual adapter/K4 path. Check extents,
row metadata, local/global destination translation, degree/correction seeds,
state replicas and completion barriers. G ends before adapter/R begins in
the selected sequential implementation. Adapter and R overlap internally;
do not add their elapsed times as though they were sequential.

Measure host preparation/rebin/relaunch separately with a fixed Release host
binary, CPU affinity and repetitions. State exactly which preparation, DMA,
launch/wait and publication events each resident/setup-inclusive result covers.
Prove the windows close without missing or double-counted work.

## Phase 5: Spine Demo And Figure Review

Status: bounded R diagnostic available; complete admitted Spine/G+R demo pending.

Only after admission, compare common old converged state plus one batch until
convergence, first on a memory-bounded real case, then the declared matrix.
No cold/warm mixing and no substitution of one-hop for convergence. Report
Spine/G/R/adapter/host windows and their shares, not just a total speedup.

Fig. 7 needs new FPGA runs for a newly routed baseline. Fig. 8 must be rerun if
G or host preparation changes. Fig. 9 needs fresh complete request traces and
energy replay. G/R-only changes do not numerically invalidate Spine-only
Fig. 10 attribution or Fig. 11 fitting; their existing evidence limits remain.
Keep paper and frozen handoffs unchanged. Deliver a separate evidence package.

## Execution And Delivery

Use unique raw attempt paths under `/data/chuxiao/experiments/`, process time
and address-space bounds, explicit memory reserve and whole-service cgroups.
R parallelism is bounded by measured RSS. Current hardware launches follow
the [memory-admitted concurrent policy](hardware_validation/README.md#memory-admitted-concurrent-routing):
reserve each active tool's full hard budget and the system reserve, then
launch when they fit. Other FPGA tools need not exit. Keep the earlier queue
records intact. No other users' processes or system caches are changed.

This folder owns the plan, interpretation, compact evidence and reproduction
guide. Code has one owner at `spine_cycle_sim/experiments/evaluation_impact/`
and `cpp/tests/evaluation_impact/`; preparation, execution and analysis are
separate. Push reviewed checkpoints with their failures and remaining gates.
Do not mark the overall baseline objective complete because a harness passes.
