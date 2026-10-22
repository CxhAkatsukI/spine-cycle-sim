# Finite Prefetch And Compaction Candidate

The finite reader/compactor is owned by the C++ core and shared by the
standalone diagnostic and a default-off complete-R experiment. The legacy
`ReGraphPmaAdapter` and default profiles are unchanged. Complete convergence
passes correctness, not performance retention or hardware timing calibration.

| Owner | Responsibility |
| --- | --- |
| `cpp/src/detail/prefetch_compact/reader.hpp` | Resource contract, state and component interface |
| `cpp/src/detail/prefetch_compact/requests.hpp` | Shared-master arbitration, reservations and actual AXI returns |
| `cpp/src/detail/prefetch_compact/join.hpp` | Banked metadata selection and bounded segment pipeline |
| `cpp/src/detail/prefetch_compact/compactor.hpp` | Stable live-lane packing within one source-cache window |
| Local `reader.hpp`, `compactor.hpp` | Thin diagnostic aliases of the core owners; no duplicated implementation |
| `cpp/src/routed_regraph/input.cpp` | Private legacy/experimental input owner and finite FIFO lifecycle |
| `sink.hpp` | Throttled diagnostic consumer and packet/window ABI checks |
| `transport_probe.hpp` | Single-initiator beat-issue probe, with exact payload and arbitration ledgers |
| `../prefetch_compact_test.cpp` | Synthetic correctness, ring wrap and backpressure |
| `../prefetch_compact.cpp` | Frozen real-input diagnostic, independent weighted CSR gate |
| `cpp/tests/routed_regraph/compact_input_tests.cpp` | Complete-R empty, throttled, multipart, source-window and TLAST bounds |

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

The explicit `RoutedInputPath::kPrefetchCompactedExperimental` selection
connects to the real Scatter/source/Gather/Apply/writeback path. Ingress and
Scatter stop at TLAST, bounded by the physical packet count, and never eat
the next partition. Legacy fixed-count operation remains the default. The
candidate requires positive weighted SSSP and sufficient finite parent credits;
unsupported configurations are rejected rather than silently approximated.

All 36 fresh Release core tests pass, as do twelve full-convergence controls
and eight exact old-row replays. The fresh SST plugin reproduces all five
default-path regressions; the experimental selection is not exposed through
SST. It remains 2.591 / 2.197 times strong A4 in the declared case, so neither
correctness nor faster diagnostic reads admit a replacement baseline.
See the [complete-convergence record](../../../../docs/experiments/comparisons/grasu_regraph_stage_validation/evaluation_impact/r_bank_stream/prefetch_compact/CONVERGENCE.md).

The separate `prefetch_source` harness arm explicitly selects
`RoutedSourceLoading::kIndependentExperimental`. Scatter loads at most one
returned source line per cycle while preserving its two 4096-vertex banks,
one-window lookahead and finite AXI/FIFO path. Concurrent cache loading and
edge access is an architecture assumption, not routed timing evidence.
The edge-coupled default remains unchanged. All sixteen convergence rows,
twelve exact old replays, 36 core tests and five default SST regressions pass;
the new prediction is still 2.519 / 2.150 times strong A4. See the
[source-loading contract and result](../../../../docs/experiments/comparisons/grasu_regraph_stage_validation/evaluation_impact/r_bank_stream/prefetch_compact/SOURCE_LOADING.md).

Reader counters include accepted physical extent, directory and PMA beats.
`max_buffered_segments` is a conservative reservation-capacity bound derived
from both PMA rings, not a measured simultaneous queue occupancy. It is not
used to alter timing.

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
