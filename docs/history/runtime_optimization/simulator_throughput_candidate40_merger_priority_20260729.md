# Simulator throughput milestone 15: exact merger wakeup priority

## Scope

When the ReGraph merger owns a pending output, only output-space availability
can make it progress. The previous event-driven guard also accepted input-data
notifications in that state, so an upstream push could wake the merger even
though the full output FIFO still blocked it. This change gives the pending
output state priority and ignores irrelevant input wakeups.

No architectural state transition is skipped. The change only removes
component invocations that are provably unable to alter state or counters.

## Controlled result

Frozen run: `syn_spread_e512__residual_pagerank` from
`shared_comparison_candidate10_k1_multipart_v4_20260728.json`, using the normal
`-O3 -DNDEBUG -flto` build and direct DRAMSim3 transport.

| System | Candidate 24 host s | Candidate 40 host s | Speedup | Simulated cycles |
|---|---:|---:|---:|---:|
| Spine | 2.790 | 2.696 | 1.035x | 4,778,979 |
| GraSU+ReGraph | 28.327 | 27.608 | 1.026x | 15,310,428 |

The controlled geometric-mean speedup over Candidate 24 is **1.030x**. Host
wall time is noisy at this scale; the structural profile is the important
result. At a 1,000-cycle sampling period, merger evaluate samples fall from
14,362 in Candidate 39 to 3,903, while gather remains at 3,945. The remaining
dominant work is AXI/backend retry processing and active DRAMSim3 clocking.

## Exactness gate

The fail-closed comparator against Candidate 24 reports PASS:

- all 356 pre-existing result fields are identical;
- both complete `result.json` files are byte-identical; and
- all 26 DRAMSim3 JSON files are byte-identical.

The candidate plugin SHA-256 is
`b6a9a0b6982ff2657be42e66a685213028f2fa97be118043bbc9a65d66da1ba0`.
Compact evidence is committed under
`docs/evidence/simulator_throughput_candidate40_merger_priority_20260729`.
Raw evidence remains under `/data/tmp/chuxiao/` in the matching Candidate 40
directories.

## Validation

The shared-core suite (105 tests), GraSU suite (29 tests), and full Python
suite (586 passes, five expected skips) pass. `git diff --check` is clean.
