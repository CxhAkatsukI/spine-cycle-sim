# Finite PMA Input Into Original A4

This control changes the input representation of the independent original
ReGraph A4 model, not the production SST model or routed K4 configuration.
The compact and PMA paths share `ComputeWiring`, including the original
source-property service, Scatter, Gather, merge, indexer, Apply, and four
broadcast state replicas. See the [experiment report](../../experiments/comparisons/grasu_regraph_stage_validation/FINITE_PMA_R.md)
for admission, numerical results, and reproduction.

## Ownership

| Responsibility | Owner |
| --- | --- |
| Reader geometry, timing assumptions, and counters | [types.hpp](../../../cpp/include/spine_sim/pma_adapter/types.hpp) |
| Registered finite reader and ordered segment emission | [reader.hpp](../../../cpp/include/spine_sim/pma_adapter/reader.hpp), [reader.cpp](../../../cpp/src/pma_adapter/reader.cpp) |
| PMA input policy for the shared downstream | [pma_source.hpp](../../../cpp/tests/pma_adapter/pma_source.hpp) |
| Whole-graph execution and nonintrusive state/window checks | [whole_execution.cpp](../../../cpp/tests/pma_adapter/whole_execution.cpp), [verification.hpp](../../../cpp/tests/pma_adapter/verification.hpp) |
| Sparse, cold/current/stale-copy fixture and finite-pressure tests | [fixture_data.hpp](../../../cpp/tests/pma_adapter/fixture_data.hpp), [fixture.hpp](../../../cpp/tests/pma_adapter/fixture.hpp), [reader_tests.cpp](../../../cpp/tests/pma_adapter/reader_tests.cpp) |
| Unmodified HLS source packet probe | [adapter_routing_probe.cpp](../../../cpp/tests/publication_sources/adapter_routing_probe.cpp) |
| Preparation, schedule inspection, execution, analysis, and delivery | [pma_adapter package](../../../spine_cycle_sim/experiments/pma_adapter/README.md) |
| Thin CLI and fixed experiment contract | [run_pma_regraph_control.py](../../../scripts/run_pma_regraph_control.py), [contract](../../../configs/experiments/pma_regraph_finite_control_v1.json) |

`pma_adapter_cycle` is a separate CMake library. It is deliberately not in the
SST Makefile: this experiment is not a new production model mode or a timing
multiplier hidden inside G+R. Existing numerical/SST bodies are unchanged.

## Input And Resource Contract

The reader fetches total slots, visits every source row, reads bounded PMA
segments, emits both halves in order, and drains before completing. All
memory access uses a shared finite AXI read port. Evaluation and commit are
registered; freeing a queue slot does not make that slot available earlier
in the same edge. Out-of-order responses are retired in segment order.

The declared existing HLS variant selects current/stale and hot/cold storage
using segment parity and an absolute half-index. Small fixtures deliberately
give stale copies different payloads and exercise three cache thresholds.
Rows must be contiguous and 16-slot aligned. Empty slots and out-of-partition
destinations are filtered; the original downstream dummy/source encoding is
preserved. Invalid geometry and relaunch while active are rejected.

Both matched paths have 16 input-parent credits and 16 outstanding bursts.
The old compact default of two parent credits remains unchanged. The legacy
eight-case matrix must retain every pre-edit observation exactly; the matched
compact matrix must also equal it after removing only its declared extra
credit field. Increasing this budget is not presumed harmless: equality is
tested. Other downstream resources are identical, including the configured
state-port pressure and memory latency variants.

The constructed read-only PMAs retain the original A4 task assignment and
edge multiplicity, including 64 repeated boundary entries and three
dummy-only tasks. They are not original GraSU host outputs and do not use
the routed K4 destination-modulo-four/23-channel placement. Those are
separate controls, not consequences of this resource match.

## Timing Evidence And Assumptions

The pinned HLS packet provides lowered schedules, burst reports, and top RTL.
Its row loop reads one 512-bit word per 64-bit row access, with no modeled
row-line cache. Repeated accesses to the same aligned line still generate
separate requests. Segment accesses also read one 64-byte beat. Report logical
row bytes and actual bus bytes separately; a previously correct source-packet
count of eight logical bytes per row is not its physical bus traffic.

| Fixed model setting | Value | Interpretation |
| --- | --- | --- |
| Minimum issue-to-use read latency | 71 cycles | Lower bound informed by the lowered schedule; not added after the memory response |
| Segment issue interval | 2 cycles | HLS schedule-informed constraint |
| Row decode | 2 cycles | Explicit control assumption |
| Source restart | 1 cycle | Explicit control assumption |
| Output latency | 1 cycle | Explicit registered-output assumption |
| Segment capacity | 38 | Explicit finite queue assumption |
| Common clock | 210 MHz | Matched conceptual clock, not demonstrated adapter timing closure |

The inspected packet targets 150 MHz. Its schedule does not prove physical
operation at the original-R comparison clock, nor supply measured FPGA
cycles for this new composition. The finite mock-memory backend is likewise
an assumption. Every result therefore keeps measured FPGA cycles and
publication-rate error unset. A passing state/traffic gate is not timing
calibration or reproduction of either paper.

## Windows And Interpretation

The resident window is one original PR iteration, from initial start until
all input paths drain and all four state publications are acknowledged. It
is neither a dynamic-update convergence test nor a host-inclusive window.
Full pre-Apply sums and all four state arrays/guards are compared with the
compact control and independent CSR reference, not only with a checksum.

Per-path reader, frontend, and shared-publication finish times are retained.
The frontend window excludes merge/Apply/writeback and can finish before
the reader scans trailing empty rows. Occupancy unions and intersections
describe overlap; they are not additive stage costs. Only the common start
to complete-drain windows define `(T_B - T_A4) / T_A4`, and that number remains
a modeled overhead until timing is independently admitted.
