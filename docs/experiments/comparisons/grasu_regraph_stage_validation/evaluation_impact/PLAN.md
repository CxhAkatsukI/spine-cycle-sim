# Baseline Admission Plan

## Objective

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
the pending route's memory reservation. New arbitration-stage latency is not
yet mirrored in the cycle engine; source/work parity cannot close the clock,
integrated-G or timing-retention gates.

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

Status: all twelve full-convergence executions passed state/traffic gates;
the candidate meets the 10% A4 prediction target on this fixed SSSP slice.
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
old rows before interpreting new ratios. Numerical results remain pending;
even equal credits would not equalize banks, replicas and source buffering.
Compare A with A4 separately; never pretend four Little reproduces 11+3.
Use an admitted publication case to test the original R model's timing,
independently of the A4/B retention control.

Exit: no hidden resource/work advantage and passing retention on the declared
matrix. Simulation-only closeness remains prediction evidence until timing
admission. R success cannot compensate for failed G.

## Phase 4: Compose The Baseline

Status: not admitted; do not bypass the G/R gates.

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
R parallelism is bounded by measured RSS; routing waits for its own 64-GiB
admission threshold. No other users' processes or system caches are changed.

This folder owns the plan, interpretation, compact evidence and reproduction
guide. Code has one owner at `spine_cycle_sim/experiments/evaluation_impact/`
and `cpp/tests/evaluation_impact/`; preparation, execution and analysis are
separate. Push reviewed checkpoints with their failures and remaining gates.
Do not mark the overall baseline objective complete because a harness passes.
