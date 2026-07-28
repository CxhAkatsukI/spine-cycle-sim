# Simulator throughput milestone 13: exact AXI response wakeup

## Scope

This milestone lets an AXI master sleep while every burst beat has been issued
and its only possible next state transition is a memory response. The memory
backend now owns one response-availability notifier per registered initiator.
Both the deterministic mock backend and the direct/SST backend wake the AXI
master when a response enters the architecturally visible backend queue.

The optimization preserves the old per-cycle bookkeeping during a suspended
interval. On wakeup, the AXI master bulk-adds the empty request-FIFO polls and
advances its issue round-robin pointer by the exact number of omitted cycles.
It does not sleep while an address, issueable beat, timed read beat, write
ingress stage, response output, or backend response can make progress or
accumulate a stall counter.

## Controlled result

Frozen run: `syn_spread_e512__residual_pagerank` from
`shared_comparison_candidate10_k1_multipart_v4_20260728.json`, built with the
normal `-O3 -DNDEBUG -flto` path rather than PGO.

| System | Candidate 24 host s | Candidate 33 host s | Incremental speedup | Simulated cycles |
|---|---:|---:|---:|---:|
| Spine | 2.790 | 2.625 | 1.063x | 4,778,979 |
| GraSU+ReGraph | 28.327 | 28.206 | 1.004x | 15,310,428 |

The two-system geometric-mean speedup is **1.033x**. This modest result is
useful infrastructure, not the final runtime claim: the dense G+R probe spends
most cycles with an issueable degree beat or an active pipeline component, so
it rarely reaches the newly sleepable state.

The normal-build cumulative geometric mean from the frozen original binary is
3.346x. Candidate 32 PGO remains an orthogonal build optimization and must be
retrained after larger source changes.

## Exactness gate

The fail-closed comparator against Candidate 24 reports PASS:

- all 356 pre-existing result fields are identical;
- both complete `result.json` files are byte-identical;
- all 26 DRAMSim3 JSON files are byte-identical; and
- cycles, correctness, requests, bytes, traces, stalls, DRAM commands,
  activity, and energy counters are unchanged.

The candidate plugin SHA-256 is
`5dff58d972cf79ee32da9378c0b8baadf642c0a5299d093bac275db2862eff38`.
Compact evidence is committed under
`docs/evidence/simulator_throughput_candidate33_axi_backend_wakeup_20260729`.
Raw evidence remains under `/data/tmp/chuxiao/`:

- candidate: `simulator_throughput_candidate33_axi_backend_wakeup_20260729`;
- equivalence:
  `simulator_throughput_candidate33_axi_backend_wakeup_20260729_equivalence`;
  and
- component profile: `simulator_throughput_candidate33_profile_20260729`.

## Validation and next step

The 104-test shared-core suite and 29-test GraSU suite pass, as do the focused
Python exact-equivalence and throughput-contract tests. The rejected
cross-burst blocked-intent shortcut was exact but showed no stable wall-time
gain and is not included.

The component profile shows the next target clearly. ReGraph degree AXI,
gather, merger, wrapper, and controller still poll on most of the 15.3 million
core cycles. The next milestone must use FIFO space/data notifications and
backend-capacity wakeups to suspend those deterministic wait states while
bulk-accounting every omitted stall cycle.
