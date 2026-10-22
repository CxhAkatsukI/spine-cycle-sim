# Finite Prefetch And Compaction Candidate

This test-owned architecture is deliberately separate from the production
`ReGraphPmaAdapter`, routed profiles and SST plugin. It is a hypothesis under
test, not hardware-calibrated performance or a completed integrated-R result.

| Owner | Responsibility |
| --- | --- |
| `reader.hpp` | Resource contract, state and component interface |
| `requests.hpp` | Shared-master arbitration, reservations and actual AXI returns |
| `join.hpp` | Banked metadata selection and bounded segment pipeline |
| `compactor.hpp` | Stable live-lane packing within one source-cache window |
| `sink.hpp` | Throttled diagnostic consumer and packet/window ABI checks |
| `transport_probe.hpp` | Single-initiator beat-issue probe, with exact payload and arbitration ledgers |
| `../prefetch_compact_test.cpp` | Synthetic correctness, ring wrap and backpressure |
| `../prefetch_compact.cpp` | Frozen real-input diagnostic, independent weighted CSR gate |

## Explicit Architecture

Each of four frontends has one shared 512-bit AXI master, <=16 parents of
<=16 beats, one 1024-row directory cache, two 256-line reserved PMA rings,
a two-stage segment pipeline and a 16-segment FIFO. Directory words come
only from real reads; one returned beat writes eight banks. An eight-bank
priority selector visits at most eight empty rows per cycle and consumes
at most one physical segment per cycle. Directory availability pays three
cycles and the segment pipeline pays two. Read use retains the existing
71-cycle minimum; Mock latency and backend credits remain unchanged.

The compactor accepts at most one 16-slot segment per cycle, stably selects
live weighted lanes into 32 slots and publishes at most one eight-lane packet
per cycle through a depth-two/two-cycle pipeline. It may cross rows but never
4096-source cache windows. A partial packet is padded at a window boundary;
an all-dummy terminal/window still has an explicit packet. Finite queues
propagate backpressure. Every physical PMA slot is still read and counted.

This pays modeled pipeline/storage costs but is **not a synthesized timing
or resource guarantee**. The returned AXI parent aggregate is consumed and
validated as well as the progressive beats; it is not an uncounted data path.
The reader stops issuing trailing directory tiles once all physical slots
are consumed, then drains already-issued reads before reporting completion.

The variable packet count is intentionally not wired to production R's
fixed-count ingress/scatter. Promotion needs a separate end-marker contract,
fresh core/SST gates and complete convergence controls. Faster diagnostic
reads alone cannot admit the baseline or authorize replacing figures.

## Transport Observation

The synthetic executable also runs a 512-beat continuous read with one
initiator, latency three and 32 backend credits. Registered arbitration
produces 511 issue gaps of two cycles; its single-initiator unregistered
control produces 511 gaps of one cycle. Forward/reverse registration is
checked in both modes. This isolates the existing request/grant handshake;
it does not change the candidate's registered backend, prove a hardware
issue interval, or admit unregistered arbitration for contending clients.

Real-input schema 2 adds read-only per-worker and shared transport counters.
Every schema-1 observation replays exactly, including cycles, requests,
traffic, packet counts and bounded-storage peaks. Detailed reproduction and
retained raw-output hashes are in the
[study guide](../../../../docs/experiments/comparisons/grasu_regraph_stage_validation/evaluation_impact/r_bank_stream/prefetch_compact/README.md).
