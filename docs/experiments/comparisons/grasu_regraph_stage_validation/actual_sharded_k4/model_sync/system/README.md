# Complete SSSP Candidate Composition

This checkpoint connects the routed adapter, input forwarding, Scatter,
dedicated source readers, Gather, ordered mux, merger, Apply and acknowledged
source-state writeback into one executable candidate. It is **not** a matched
FPGA timing result, a selected SST architecture profile, or an original-A4
performance comparison. Existing v8 runs and paper/figure inputs are untouched.

Use the [machine-readable result](system.json), [raw index](system_raw_index.json)
and [frozen evidence archive](raw_system.tar.gz) together. All 21 CTest
executables pass, and all five predeclared legacy SST cases preserve every
result field with no ignored fields. Candidate and legacy gates bind the
same final source snapshot and a freshly built plugin, not `build/sst`.

Read the [frontend provenance correction](../frontend/README.md) first:
the measured SSSP wrapper XO has four independent read masters. The later HLS
worktree's two pairwise services are a different target. This candidate uses
the measured four-reader topology. Its test clock is 150 MHz.

The later [pairwise source checkpoint](source_pairs/README.md) adds an
explicit default-off selection for that different HLS target. The frozen
results below remain the original four-reader evidence.

## Code Review

| Owner | Responsibility |
| --- | --- |
| `cpp/include/spine_sim/routed_regraph.hpp` | Separate candidate configuration, system API and event/counter contracts |
| `cpp/src/detail/routed_regraph_system.hpp` | Private ownership and wiring declarations |
| `cpp/src/routed_regraph/admission.cpp` | Geometry, ABI, capacity, source-lookahead and initial-state checks |
| `cpp/src/routed_regraph/resident_memory.cpp` | PMA runtime placement and resident state serialization |
| `cpp/src/routed_regraph/composition.cpp` | Four frontend chains, nine physical masters and finite logical clients |
| `cpp/src/routed_regraph/transport.cpp` | Globally ordered Gather mux and acknowledged active-count write |
| `cpp/src/detail/routed_regraph_transport.hpp` | Registered stream bridges and known-count input forwarding |
| `cpp/src/routed_regraph/rounds.cpp` | Independent per-worker adapter/lksg dispatch and round completion |
| `cpp/src/routed_regraph/system.cpp` | Public API, readback, conserved counters and timeout diagnostics |
| `cpp/tests/routed_regraph/system_tests.cpp` | Complete-state software oracle and bounded integration tests |
| `spine_cycle_sim/experiments/sharded_k4_stages/model_system.py` | Build/run/source identities and complete matrix validation |
| `spine_cycle_sim/experiments/sharded_k4_stages/system_delivery.py` | Immutable candidate and unchanged-legacy evidence package |

The existing adapter, Scatter/source and extracted arithmetic owners are
reused. No whole-system speed multiplier or candidate conditional is inserted
into the legacy `grasu_regraph.cpp`. Both CMake and the SST Makefile compile
the new sources; compiling them does not select this topology in SST.

## Scheduling And Memory Contract

- Destination shard `p` uses worker `p % 4`. Each worker's adapter and lksg
  invocations form **separate** chains, matching the host dependencies.
- A counted input forwarder consumes exactly `physical_slots / 8` packets.
  The adapter can start the next invocation with the previous tail still in
  its output FIFO. It does not wait for the entire compute bundle.
- Each lksg invocation resets Gather. Its completion waits for counted ingress,
  Scatter's source-end drain, and the last Gather output accepted into AXIS.
  Its output FIFO can still contain that invocation's tail at the next start.
- The mux consumes exactly 32,768 two-vertex rows per shard, in global shard
  order. One merger, Apply and writeback run across all padded destinations
  per round, rather than restarting for each shard.
- Four adapter AXI masters and four dedicated source-read masters are explicit.
  Source readers 0/2 reach HBM23, 1/3 reach HBM24. Source writes share readers
  0/1's masters. Apply read/write/status share the ninth master on HBM30.
  Finite registered logical-client arbitration does not create extra bandwidth.
- Source request/response streams have separate internal and external FIFOs
  and registered bridges. The default depths are 8 and 16, respectively.
- Empty source-0 rows retain the routed host's real 16-slot dummy reservation.
  Empty destination shards therefore incur PMA, source-cache, reset, output,
  Apply and writeback costs. They are not zero-cost skipped tasks.
- State allocations include every padded 65,536-vertex destination partition.
  Padding starts at zero and remains zero, including both source replicas and
  both buffers. This differs from the legacy out-of-range INF branch.
- A source-window lookahead beyond that allocation is rejected. No unallocated
  data is silently synthesized as zero. The test includes this rejection.
- Extreme initial distances whose largest possible walk over the configured
  round horizon could reach the HLS 31-bit infinity are conservatively rejected.
  The extracted generic arithmetic uses a different saturation limit. This
  guard admits the tested finite domain without changing the frozen arithmetic
  or claiming that its untested overflow behavior matches HLS.
- Apply publishes active count through an acknowledged four-byte write.
  The round completes only after all kernel chains, streamed data, writes,
  logical clients and physical masters drain. The next round reads the other
  source buffer; it cannot begin at a premature Gather-only boundary.

The API accepts a post-update weighted PMA and explicit old-state/frontier.
It models **resident compute**, not GraSU maintenance, host preprocessing,
DMA, launch/wait, or host relaunch latency. Those boundaries must be composed
and compared separately in the later hardware experiment. SSSP is the only
admitted algorithm here; CC/PR are not silently inferred from this wrapper XO.

## Validation Matrix

The complete executable gate has 13 executions:

| Input | Scope |
| --- | --- |
| 129 logical vertices | Cold SSSP, four rounds; normal/reverse registration |
| 65,569 logical vertices, two shards | Warm SSSP, cross-shard propagation, four rounds; both orders |
| 262,273 logical vertices, five shards | Warm SSSP, repeated worker-0 invocations, five rounds; both orders |
| 129 vertices, tight AXI/backend capacities | Two-credit pressure and shared-master backpressure; both orders |
| 129 vertices, stop-after-last disabled | Trailing metadata work remains charged; both orders |
| All-empty graph | Dummy reservation and all padded work; one converged round |
| Fixed two-round run | Exact intermediate state, explicitly not convergence |
| One-round limit | Expected nonconvergence failure, with exact partial state; not admitted as a converged result |

Thus eleven executions converge, one intentionally uses a fixed-round
boundary, and one verifies the failure boundary. Nine invalid input/configuration
cases must be rejected. The oracle computes synchronous SSSP independently of
the Gather/Apply implementations, including the per-round active-bit state.

Every execution compares all logical values, all padded values, and both copies
of both source buffers. It checks the convergence/fixed-round boundary,
invocation mapping and chain dependencies, status acknowledgement, edge and
packet counts, 256 source lines per block, Gather/mux rows, Apply reads/writes,
two source writes per output burst, and accepted/completed AXI parents/beats.
Backend requests are independently reconciled with the AXI beat ledger.
Paired registration orders must preserve the entire returned counter/event
record and every cycle, not just the final distances.

The first integration attempts hit a 6,000,000-cycle test cap. The five-shard
case actually requires 6,022,630 cycles under the declared model. A diagnostic
check found no stale scheduler readiness bits; both orders later completed
with identical results and cycles under the increased 20,000,000-cycle cap.
No scheduler or arithmetic fix was required. The failed raw attempts and
profiling output are retained, rather than described as a hardware deadlock.
An earlier compile attempt also exposed GCC's temporary-reference warning;
metadata region descriptors are now copied instead of binding temporaries.
That initial compiler error was observed in the terminal transcript rather
than saved as a raw log file; the archive must not be read as containing it.

## Timing Limits

These cycles are predictions under explicit finite components. Memory in this
integration gate is the registered mock backend, not DRAMSim3 or FPGA.
Adapter defaults remain the schedule-informed 71-cycle minimum read-to-use,
six-cycle row control and two-cycle segment issue interval. Scatter defaults
remain latency 4, II 1, capacity 5; stream bridges add a registered token stage.
Gather, Apply and source writing retain the extracted component assumptions.
Shared-master arbitration is registered round-robin, not a reconstructed
Vitis interconnect arbitration trace. Host launch gaps are not free measured
device time: they are outside this test's declared window.

Neither this correctness gate nor legacy equivalence establishes matched
hardware latency. The next gates are an explicit artifact-bound SST candidate
profile, bounded matched hardware cases (including device/host window and
memory mapping), and original-A4 versus actual optimized K4 with matched
arithmetic, state, rounds and resources. Preserve all timing mismatches.

## Reproduce

Use fresh directories from the simulator root:

```bash
cmake -S . -B build/k4-system-review -DCMAKE_BUILD_TYPE=Release
python3 scripts/validate_sharded_k4_system_model.py \
  --core-build build/k4-system-review --output results/k4-system-review
cmake --build build/k4-system-review -j2
ctest --test-dir build/k4-system-review --output-on-failure --timeout 600
```

The runner freezes source/compiler/build identities, uses CPU affinity 112-113,
an 8-GiB address-space limit and a 16-GiB free-memory reserve. Build and execution
timeouts are 300 and 600 seconds. Its system report distinguishes the expected
limit failure from converged executions. For another machine, adjust affinity
explicitly and record it; do not present wall time as FPGA latency.

Local campaign root:
`/data/chuxiao/experiments/sharded_k4_composition_sync_20261011/`.
The raw legacy baseline is the preceding frontend checkpoint's `legacy_final`,
not the older pre-source-correction component package.

Final candidate execution takes about 21 seconds wall time with roughly
61 MiB maximum process RSS; the five-case legacy check takes 246 seconds with
roughly 144 MiB maximum process RSS. These are execution-safety observations,
not FPGA-performance numbers or aggregate concurrent-process RSS measurements.
