# Original-ReGraph Little Input Path

This independent component family extends the finite
[Gather/merge core](original_regraph_little_gather.md). It does not replace the
ported G+R model or alter the production SST plugin. Its current boundary is
resident padded edge/source memory through Little Scatter and optionally the
global merged-property FIFO. Apply, degree reads, property writeback, Big
pipelines, mixed scheduling, preprocessing and host orchestration are outside
this boundary.

## Ownership

| Module | Responsibility |
| --- | --- |
| `original_regraph/frontend_types.hpp` | Explicit edge/source packets, read-port contract and default frontend pipeline timings |
| `original_regraph/detail/wire.hpp` | Little-endian 512-bit payload decoding and read acknowledgement validation |
| `original_regraph/edge_reader.hpp/.cpp` | Padded edge extent, streamed AXI read, destination localization, finite reader pipeline |
| `original_regraph/source_memory.hpp/.cpp` | One request-dependent 4K-vertex source window at a time, allocation bounds, complete response/acknowledgement and partition termination |
| `original_regraph/little_scatter.hpp/.cpp` | Eight replicated ping-pong source buffers, original lookahead/request protocol, held edge and finite update pipeline |
| `cpp/tests/original_regraph/frontend_support.hpp` | Options, deterministic edge fixture, encoding and scalar source oracle |
| `cpp/tests/original_regraph/frontend_wiring.hpp` | Owned scheduler, queues, AXI ports, memory backend and optional Gather/merge wiring |
| `cpp/tests/original_regraph/frontend_execution.hpp` | Output checks, request traces, drain conditions and conservation measurements |
| `cpp/tests/original_regraph/frontend_tests.cpp` | Fixed positive, pressure, resource and allocation-boundary matrix |

Headers and implementations live under `cpp/include/spine_sim/` and
`cpp/src/`, respectively. Numerical components contain no experiment runner
or report-packaging logic. The experiment owner remains
`spine_cycle_sim/experiments/original_regraph_validation/`; its frontend
analysis, execution and delivery modules have separate responsibilities.

## Original Source Semantics

The author revision is `365456826cef495285383d939907f847e05ad74b`.
`acc_template/kernel_little_gs/kernel_scatter_gather.cpp` localizes each
destination by subtraction followed by a 20-bit assignment whose top bit is
replaced by the original dummy flag. The model preserves the lower 19 bits
even for dummy tuples; it does not silently canonicalize them.

`acc_scatter.h` maintains eight source-buffer replicas, each with two
4096-vertex windows. A window is released for edge lookup when the first line
of the following window arrives. Remaining lookahead responses are drained
after the final edge. Those responses still consume source-memory bandwidth.
The model validates initialized cache lines and disallows a physical edge
burst that spans source windows; preprocessing must provide admitted padding.

The request guard subtracts two `ap_uint<32>` values. Vitis HLS 2024.1 makes
that expression **signed 33-bit**, not unsigned 32-bit. This is verified with
a source-control static assertion and runtime check. Thus initially starting
in round 2 requests `[0,2,3]`; moving from round 0 to round 3 requests
`[0,1,3,4]`. Treating the subtraction like ordinary C++ unsigned arithmetic
would incorrectly predict a deadlock. The cycle model uses signed widened
arithmetic and checks both sparse sequences.

The original wrapper's Little partition count is an `uchar`; this component
rejects counts outside 1--255. A source request must fit the allocated property
extent, including lookahead. Missing memory is not synthesized as zero. This
does not establish that an author publication workload overreads: its actual
allocation and preprocessing still require separate admission.

## Finite Timing And Memory Assumptions

- Core clock: 210 MHz, used as a model configuration, not a measured event.
- Reader: latency 3, II 1, in-flight capacity 4. Scatter: latency 4, II 1,
  capacity 5. Gather/drain/local/global merge use the separately documented
  HLS-schedule-informed 6/3/3/4-cycle assumptions.
- Registered component FIFOs default to depth 8. A depth-1/slow-consumer
  control checks that pressure reaches the source-memory service.
- Each Little has separate fixed edge/source channels: HBM `2*i` and
  `2*i+1`, matching the generated A4 channel allocation. Apply/writeback is
  not yet connected; future property reads/writes must share their actual
  physical channel budget, not acquire extra independent channels.
- AXI: 64-byte beats, at most 16 beats/burst, 16 outstanding bursts,
  32-beat read reorder buffer, two logical parents and one address/beat/response
  per cycle. One control lowers outstanding bursts to 1.
- The current test backend has 32 channels, 64-cycle latency, one acceptance
  per channel per cycle, 512 outstanding beats/channel, a 64-entry response
  queue and registered round-robin arbitration. A control uses 128 cycles.
  These are **declared mock-memory assumptions**, not DRAMSim3 or measured HBM.
- Logical reads split through the existing AXI master. Both streamed beats
  and the full aggregate parent acknowledgement must finish. No read is
  declared complete merely because its last value was used by Scatter.

Finite pipelines are elastic model resources. HLS synthesis schedules inform
their unstalled latency/II, but do not validate cycle-exact HLS global-stall
behavior. Reported stalls are model counters, not hardware performance counters.

## Validation Boundary

The original `accScatter` is executed against a request-dependent functional
service using Vitis stream delegates. Its exact request/response sequence is
then checked against the original `littleKernelReadMemory`. This is not RTL
concurrency simulation or timing evidence. Independently, the finite model
checks every emitted tuple against a scalar source oracle; the four-Little
composition checks all 65,536 merged words against direct per-edge sums.

This checkpoint also reruns the previously accepted Gather/merge source-word,
cycle, stall, clearing and corruption controls. Its accepted result and source
capture hashes must remain exactly equal to the frozen Gather checkpoint.
Reversed registration order, repeated runs, FIFO/AXI conservation and bounded
undefined-behavior instrumentation provide additional checks, not FPGA
calibration or publication-speed reproduction.

The [study delivery](../../experiments/comparisons/grasu_regraph_stage_validation/LITTLE_FRONTEND_MODEL.md)
contains the observed results, raw attempts, provenance and reproduction
commands. Complete G, A, A4/B and host-stage conclusions remain separate gates.
