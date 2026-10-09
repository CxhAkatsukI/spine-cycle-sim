# Original Little PR State Path

This extends the [memory/frontend model](original_regraph_little_frontend.md)
inside the independent `original_regraph_cycle` library. It does not change
the production G+R/Spine components or SST plugin. The validation and raw
evidence belong to the [stage study](../../experiments/comparisons/grasu_regraph_stage_validation/LITTLE_STATE_MODEL.md).

## Ownership

| Responsibility | Interface / implementation |
| --- | --- |
| Indexed 512-bit property packet and memory targets | `cpp/include/spine_sim/original_regraph/state_types.hpp` |
| Sequential Little write indices and one terminator | `write_indexer.hpp` / `cpp/src/original_regraph/write_indexer.cpp` |
| Degree reads, original PR arithmetic, ordered finite Apply | `pr_apply.hpp` / `cpp/src/original_regraph/pr_apply.cpp` |
| Broadcast new properties, per-replica acknowledgements | `property_writer.hpp` / `cpp/src/original_regraph/property_writer.cpp` |
| Shared test memory ownership and teardown | `cpp/tests/original_regraph/memory_fixture.hpp` |
| State wiring and independent scalar oracle | `state_support.hpp` / `state_execution.hpp` in the same test directory |
| Resident source/new-property ping-pong across three rounds | `iteration_tests.cpp` in the same test directory |

The common memory fixture replaces duplicated frontend test ownership, not
production simulation logic. Registered FIFOs cannot deliver same-edge pushes.
Destruction unregisters components and destroys AXI masters before their
queues/backend, preserving callback lifetime. Tests compare the entire old
frontend analysis and Gather/source results with the frozen checkpoints.

## Functional Contract

Original PR uses signed 32-bit `prop_t`, with:

```text
score = argument + ((108 * sum) >> 7)
inverse = degree ? (65536 / degree) : 0
property = (score * inverse) >> 16
```

The model uses safe unsigned intermediates but rejects inputs for which the
original signed multiplication/addition would overflow, or degree would be
negative when interpreted as signed. This is a deliberate supported-domain
boundary, not arbitrary signed-overflow equivalence. Zero degree and degree
larger than 65,536 produce zero under the original integer reciprocal rule.
The original-source probe checks actual Apply output, the generated writer,
every output replica and untouched allocation guards; the model separately
checks all replicas against a scalar oracle.

Apply associates every 64-byte degree response with its request, retains FIFO
output order, and bounds pending plus arithmetic-live lines together. Unknown
or repeated responses are errors. Index/extent and early/end/excess checks
prevent stream termination from silently discarding work. The writer retains
each payload until every target acknowledges; a result being computed or
placed into a write queue is not completion. Restart requires complete drain.

## Resource And Timing Contract

| Resource | Default |
| --- | --- |
| Clock, model memory | 210 MHz; explicit 32-channel mock backend, 64-cycle service latency |
| Degree port | Physical channel 30; 64-byte non-stream reads, 16 outstanding |
| Property replicas | Four for A4; fourteen for the isolated default-writer component control |
| Property port placement | Odd physical channels 1, 3, ...; same backend/channel as source reads |
| Index pipeline | II 1, depth 2, capacity 3 |
| Post-degree-read Apply | II 1, modeled depth 26, capacity 27 |
| Combined Apply live-line limit | 100 |
| Writer retained-line limit | 72 |
| Ordinary stream queues | Depth 8; depth 1 pressure controls |

The original HLS reports place Apply's read-data acceptance at iteration 72
and output at 98; 26 cycles is the resulting post-read schedule separation.
The scalar arithmetic report is 23 cycles. The complete 99-cycle Apply loop
includes AXI service and must not be added on top of explicit degree memory.
Likewise the 71-cycle writer report includes the write response; the model
waits for explicit responses instead of adding another 71-cycle delay.
These report-derived constraints are not FPGA timing calibration.

Source-read and property-write directions have separate logical AXI masters
but contend on the same physical channel, limited to one backend beat per
cycle. The original HLS uses the same `gmem` bundle; this model is not a
cycle-exact reproduction of that bundle's internal read/write arbitration.
Apply/writer requests are individual 64-byte lines; automatic HLS burst
coalescing is not assumed. Finite elastic pipes and explicit credit bounds
are approximations to HLS global-stall control. Whole-R publication matching
requires these differences to be checked, not hidden in a fitted multiplier.

## Iteration Boundary

The integration fixture connects reader/source service, Scatter, private
Gather arrays, local/global merge, indexer, Apply and broadcast writes.
Four Little pipelines process one 65,536-destination partition for three
fixed PR iterations. Source and destination buffers swap after every fully
acknowledged round; later input properties are read from resident device
payload written by the preceding round, not recomputed/copied by the host.

Graph upload, degree initialization, inactive-buffer guard preparation and
launch/setup are outside this synthetic resident-kernel window. The fixture
uses small explicitly defined positive initial properties and argument 3,
not the publication's graph initialization or convergence criterion. Full
partition scheduling, Big/mixed execution, DBG preprocessing, original G,
adapter overhead and host composition remain separate unvalidated stages.
