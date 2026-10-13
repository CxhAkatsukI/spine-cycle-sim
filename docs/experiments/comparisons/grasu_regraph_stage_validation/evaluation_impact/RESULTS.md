# Diagnostic Findings

## Decision

**Do not admit the current complete G+R baseline yet.** The same-input G
test exposes an implementation-performance mismatch. A passing R prediction
cannot compensate for that, and neither control reproduces published FPGA
rates. The paper, frozen figure package and production SST plugins are unchanged.

This checkpoint implements the first bounded tests in [the plan](PLAN.md).
It does not finish the overall original-performance validation objective.

**Subsequent checkpoint:** the [parallel-search study](parallel_search/README.md)
adds a default-off core candidate, 84 prediction runs and isolated HLS attempts.
Its larger batches still fail performance retention and its estimated clock
misses 200 MHz. The numerical observations and verification counts below
describe the initial diagnostic; the linked checkpoint owns the new results
and updated regression limitations. Neither checkpoint admits complete G+R.

## G: Same Inputs, Different Performance

The current single-window `GraSuPmaUpdateSystem` and independent original
source16 model receive the same initial PMA and prepared update words. The
fixture has 524,288 local destinations, two nonempty source rows, 262,144 hot
and 64 cold segments, sixteen 32-bit slots per segment. All keys use weight
one so the packed weighted ABI has a reversible common ordering; this is not
an admission of every weighted or conflicting-key workload.

Both arms use 200 MHz, four shared physical banks, 32 bank credits and the
same latency assumption. The event window starts with prepared inputs resident
and ends with update and memory drain. Host reservation/preparation is excluded
from both. This is not a full 23-channel sharded-system experiment.

All twelve runs preserve complete PMA state, update-route counts and physical
traffic conservation. The four nonempty comparisons are:

| Memory latency | Updates | Original cycles | Current cycles | Current/original |
| --- | --- | --- | --- | --- |
| 64 | 64 | 533,081 | 16,068 | 0.0301 |
| 128 | 64 | 1,057,817 | 30,532 | 0.0289 |
| 64 | 4096 | 577,403 | 1,441,620 | 2.4967 |
| 128 | 4096 | 1,142,267 | 2,740,180 | 2.3989 |

Thus the current model is approximately 33--35 times faster for the small
batch, but approximately 2.4--2.5 times slower for the larger batch. Neither
direction is a match within 10%. There is no justified common scaling factor.
The empty-batch control records original startup costs of 532,619/1,056,907
cycles versus zero current cycles; it is retained, not used as updates/second.

### What Explains The Difference

The original source-derived model loads and writes back its complete hot
cache each batch. Even an empty batch transfers 16,777,216 bytes each way.
The current direct path avoids that fixed cost. For 64 updates, original
read/write traffic is 16,786,432/16,779,264 bytes, versus 11,264/4,096 bytes
for current G.

For 4096 updates, original read/write traffic is 17,430,528/16,781,312 bytes,
versus 911,360/262,144 current bytes. Current G nevertheless takes longer:
the difference is not explained by byte volume alone. Current direct search
and HBM hot read-modify-write sacrifice concurrency relative to the original
parallel search and URAM path. The matched search work is unchanged: 64/4096
row accesses and 768/72,960 binary probes, respectively.

Inspected production HLS build logs explicitly enable
`GRASU_COMPACT_HBM_PORTS` for search and
`GRASU_PURE_PIPELINE_DIRECT_CACHE` for hot updates. Inspected HLS source
selects `bin_search_direct` and `process_cache_direct` under those flags.
Consequently the structural difference exists in the hardware port too;
this is not permission to insert an unexplained simulator correction.
These observations identify candidate causes, not a measured per-stage
hardware attribution or a speed prediction for the whole sharded system.

The independent original model remains a declared timing prediction. Its
source16 geometry differs from the paper's eight-slot geometry, and original
workload conversion, denominator and timing admission are still unresolved.
Even a matching model ratio would not reproduce the original paper's rate.

## R: Complete Warm-Update Convergence

The predeclared twelve-run matrix compares original compact four-Little A4,
unchanged cross-row K4 and the bank-stream candidate. All use the fixed Amazon
real-ID slice: 258,046 vertices, 1,450,899 edges, four destination shards,
old converged SSSP distances and three source-zero weight decreases. Inputs
are already resident; G, seed preparation, DMA, launch and host orchestration
are excluded from every arm. The independent frontier and shortest-path
oracles require 46 rounds, not one-hop completion.

All twelve executions completed and passed the final-state, active-trajectory,
physical-request and traffic gates. Both registration orders produce identical
observations. Each arm takes 46 rounds; A4 also checks every intermediate state
against the synchronous oracle. No model coefficient changes between latency
controls. The complete reports are preserved in the [evidence index](evidence/index.json).

| Memory latency | Original A4 cycles | Cross-row K4 cycles | Bank-stream candidate cycles | Candidate/A4 | Cross-row/candidate |
| --- | --- | --- | --- | --- | --- |
| 64 | 30,740,788 | 244,269,384 | 32,160,486 | 1.0462 | 7.5953 |
| 128 | 59,442,350 | 431,605,442 | 57,582,524 | 0.9687 | 7.4954 |

Thus the candidate is 4.62% slower than A4 in the 64-cycle control and 3.13%
faster in the 128-cycle control. Both meet the predeclared two-sided 10%
compute-prediction target for this case. This is a result, not a timing fit:
the latency control changes equally for all arms, and no observed total-time
ratio is applied to a component. It does not close the broader R admission gate.

The candidate's complete read traffic is 2,021,232,640 bytes versus
2,021,226,752 bytes for cross-row K4: effectively the same volume, with a
small directory-tail difference. A substantial cycle improvement here comes
from transaction organization and overlap, not eliminating most bytes.
That is another reason not to rescale Figure 9 by an elapsed-cycle ratio.

Original A4 and K4 still differ in endpoint layout, source-state physical
banks, state replicas and parent credits. Four Little frontends do not by
themselves establish strict resource equality. This is a compute-path
prediction control, not an original 11+3 publication reproduction, FPGA
measurement or universal result across algorithms/datasets.

The resource differences are explicit rather than hidden inside the ratio:

| Resource | Original A4 | Both K4 arms |
| --- | --- | --- |
| AXI endpoint / master organization | 13 endpoints on 9 masters | 9 masters |
| Physical source-state banks | 4 | 2, shared by four frontends |
| Apply parent-request window | 2 | 16 |
| Final state replicas | 4 | 3 plus status |
| Clock | 150 MHz | 150 MHz |

The candidate additionally uses 1024-row directory tiles, two 256-line bank
FIFOs (32 KiB total), a sixteen-segment queue and progressive read-beat
delivery. These architectural choices require matching HLS and hardware
validation; they are not free corrections to an unchanged kernel. The queued
route is not yet hardware-timing evidence. Neighboring workloads,
CC/ResPR, original mixed-topology timing and strict resource controls remain
unfinished.

Attempt v1 stopped at the declared 200-million-cycle bound during cross-row
round 38; it did not reach 46-round convergence. Attempt v2 raises the total
bound to 1.5 billion cycles and uses four independent processes, without
changing numerical timing. The failed attempt remains part of the delivery.

## Consequences For Figures 7--11

| Figure | Defensible consequence now |
| --- | --- |
| 7 | Old numbers remain measurements of their recorded bitstreams. An improved baseline requires new matched hardware measurements; do not replace hardware bars with these predictions. |
| 8 | R propagation is outside the update-only window. The G difference is directly relevant: reassess G/layout/host preparation, then rerun if changed. Do not divide old throughput by an R speedup. |
| 9 | PMA traversal optimization changes physical reads and their timing. Rerun complete G+R request traces and DRAMSim3 energy after implementation promotion. New cycle totals alone cannot update energy. |
| 10 | This is Spine-only normalized predicted attribution. G/R-only changes do not change its raw Spine stages; the lack of stage-level FPGA calibration remains. |
| 11 | This fits Spine realized work to Spine simulator cycles. G/R-only changes do not change its dataset or fit and do not add hardware validation. |

The bounded R demo quantifies a change to one baseline compute path. It is
not a newly validated full Spine/G+R speedup. Full E2E impact needs G,
adapter/R and host windows; overlapping adapter and compute windows cannot
be added as if independent sequential stages. No old figure is silently
rescaled, and no conclusion is generalized from this single SSSP slice.

## Reproduction And Safety

Use the commands in [the guide](README.md). All runs use fresh Release builds,
source/input/binary hashes, recorded affinity, per-process time/address-space
bounds and outer cgroup containment. The G matrix completed with about
329 MiB peak service memory. The complete R service finished in 17 minutes
41 seconds with about 1.1 GiB peak service memory. It used an 8-GiB maximum, 7-GiB high
threshold, no swap and four processes, each capped at 4-GiB address space;
launch reserves 24 GiB plus all four address-space limits system-wide.

The existing queued hardware route retains its separate 64-GiB available-
memory admission, 40-GiB cgroup maximum and runtime live-memory watchdog.
This checkpoint does not launch a second route or alter its frozen sources.

Numerical changes are confined to independent diagnostic harnesses; the
production core and plugins are not promoted or overwritten. Tests reject
incomplete matrices, changed registration-order observations, nonconvergence,
unclosed timing windows and insufficient memory. The next engineering task
is the actual HLS-feasible G correction, not retuning model coefficients.

The [committed evidence capsule](evidence/index.json) includes the complete
matched-G report, complete R convergence report, retained failed attempt,
report hashes and inspected G source/build-flag references. Large graph,
binary and stdout artifacts remain at their indexed raw paths under
`/data/chuxiao/experiments/baseline_evaluation_impact_20261012/`; this is an
indexed checkpoint, not a self-contained FPGA build or new figure handoff.

### Verification Scope

The focused experiment/admission tests and document-organization checks pass.
The earlier `test_stage_validation_delivery.py` suite retains five passing
tests and one failing test with 23 historical source-hash assertions. That
test compares current code with the earlier refactor/finite-control snapshot;
subsequent already-committed changes, including independent AXI read/write
channels (`14daf44`), changed those identities before this diagnostic.
This checkpoint changes none of those numerical production files. The new
run freezes and verifies its own current source/input/binary identities.
Historical reports, hashes and assertions are not rewritten to conceal the
failure; this is not a claim that the complete repository test suite passes.
