# Original GraSU Finite Composition

This independent source16 study is not a replacement for the production
G+R model or SST plugin. Start with the
[study status](../../experiments/comparisons/grasu_regraph_stage_validation/README.md)
and the [original source control](original_grasu_source_path.md).

## Owners

| Responsibility | Owner |
| --- | --- |
| Segment ABI, sorted insertion/deletion, response checks | `cpp/include/spine_sim/original_grasu/types.hpp`, `cpp/src/original_grasu/types.cpp` |
| Four-way ordered merge dispatch and finite cache/DDR fanout | `routing.hpp/.cpp` |
| Edge AXI stream and 64 search lanes with eight BIPA ports | `search.hpp`, `edge_reader.cpp`, `search.cpp` |
| Complete hot-region load/writeback and sixteen banked PEs | `hot_store.hpp/.cpp` |
| Two sixteen-lane DDR subcores per half | `ddr.hpp/.cpp` |
| Four-bank memory fixture and wiring | `cpp/tests/original_grasu/memory.hpp`, `system.hpp` |
| Binary input, all-buffer oracle and nonintrusive execution | `fixture.hpp`, `execution.cpp` |
| Preparation, bounded execution, independent validation and packaging | `spine_cycle_sim/experiments/grasu_finite/` |

All C++ component paths in the first five rows are relative to
`cpp/{include/spine_sim,src}/original_grasu/`. Public interfaces are small;
no new mode or numerical behavior is inserted into the existing native port.
The CMake-only library links the unchanged core FIFO, AXI and scheduler
primitives. It deliberately does not enter `cpp/sst/Makefile`.

## Connections And Resource Limits

Each original search kernel has one 64-bit edge bus, four 64-bit binary-table
buses and four 64-bit row-offset buses. All nine map to the same physical
DDR bank. The separate cache and DDR update buses are 512-bit. The fresh
original `bin_search.v` parameters establish this width difference; an
8-byte AXI payload must not be mislabeled as a 64-byte DRAM burst.

Search lanes are fed and merged in the original round-robin order. Each
BIPA port has sixteen pending-request credits, including completed responses
waiting for ordered delivery. The generic AXI fixture can complete parents
out of order, so transaction IDs select response owners and a bounded reorder
buffer restores BIPA issue order. This bridge is a declared fixture behavior,
not evidence that the original physical AXI master reorders requests.

The top dispatcher restores global update order across four search streams.
Segment parity selects the even/odd half; the half-segment hot threshold
selects cache or DDR. Cache uses sixteen PE FIFOs; DDR uses thirty-two,
interleaved between two subcores. Cache end fanout is sequential; DDR end
fanout is parallel with independently retained backpressure.

Cache-even shares bank 0 with search 0; DDR-even shares bank 1 with search 1.
The odd half similarly uses banks 2/3. The four ports of each DDR kernel alias
one physical PMA buffer. Every invocation, including an empty batch, loads
and writes the complete 131,072-segment hot region in both halves:
16 MiB of reads and 16 MiB of writes per batch.

The default test memory has registered round-robin bank arbitration, minimum
64-cycle service latency, at most one accepted beat per bank per cycle and
512 outstanding beats per bank. Ports have sixteen AXI bursts and sixteen
parent requests. FIFOs have depth two. These are explicit finite assumptions,
not a calibrated U250 controller or bandwidth measurement. Pressure controls
change latency, bank credits and FIFO depth without changing the workload.

## Timing And State Boundaries

All nine kernels begin in one simulated launch window; host preprocessing,
DMA and launch overhead are excluded. A batch completes only after every
search end, update, cache writeback and DDR write response has completed and
all FIFOs, AXI masters and the backend have drained. Components share memory,
so their completion windows overlap and are not additive stage durations.

Timing defaults are source-schedule-informed predictions, not fitted results:
search control delay 1; cache II 3, latency 7; DDR compute delay 18,
minimum sweep 161 and restart 4 cycles. The separate DDR RTL study constrains
the outer flush behavior but does not calibrate this whole-G model. Cache
same-row updates conservatively wait for the preceding write to retire.
Original URAM dependency timing still requires a separate RTL control.

The fixture intentionally covers only valid absent insertions and existing
deletions in sorted non-full source16 segments. Trace-aware reservation,
rebalancing, duplicate/absent-update policies and the original temporal workload
are not admitted by this composition test. Paper8 geometry is a separate
control, not a hidden change to the author's source16 configuration.

## Verification

Prepared fixtures cover empty, one/three, 65/257 updates, hot-only,
cold-only and three consecutive mixed batches. The C++ checker examines
every slot in all four physical buffers after every batch, including stale
copies and an end guard. Python separately regenerates final merged state,
checks every physical buffer and preserves every per-lane row/binary request
in source order. The frozen author-source executable is rerun on all eight
logical fixtures, not replaced with the new C++ state function.

Repeated executions and reversed component registration must preserve every
reported numerical field and capture hash, including stalls and component
completion windows. Physical AXI payload bytes, parent/beat conservation,
PE updates, end markers and complete drain are checked independently.
Device timing, source-word equivalence and publication-rate matching remain
different acceptance decisions.
