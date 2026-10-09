# PMA Adapter Source And Shared A4 Wiring

This owner validates the existing sharded destination-only HLS adapter on the
same logical tasks as original A4. It also extracts A4 wiring so a finite PMA
producer can later reuse the exact downstream. The
[study report](../../experiments/comparisons/grasu_regraph_stage_validation/ADAPTER_SOURCE.md)
owns accepted results; this is not an adapter-overhead timing result.

## Ownership

| Responsibility | Owner |
| --- | --- |
| Existing adapter revision, macros, matrix and limits | `configs/experiments/original_regraph_adapter_source_v1.json` |
| Thin CLI | `scripts/run_original_regraph_adapter_source.py` |
| Task-preserving source16 PMA construction | `spine_cycle_sim/experiments/original_regraph_execution/adapter/preparation.py` |
| Independent full multiset/layout/packet checks | `adapter/analysis.py` |
| Guarded source runs and identity admission | `adapter/study.py` |
| Planned extraction admission and exact whole-A4 regression | `adapter/regression.py` |
| Damaged input and actual output rejection | `adapter/validation.py` |
| Immutable raw/indexed delivery | `adapter/delivery.py` |
| Original A4 input producer | `cpp/tests/original_regraph/whole_graph/compact_source.hpp` |
| Shared downstream and independent per-path coordinator | `whole_graph/compute_wiring.hpp` |
| Compatible A4 wiring name | `whole_graph/wiring.hpp` |
| Unchanged HLS source call and actual AXIS capture | `cpp/tests/publication_sources/adapter_probe.cpp` |
| Bounded source input and independent logical multiset admission | `publication_sources/adapter/input.hpp` |
| Focused tests | `tests/test_original_regraph_adapter.py` |

## Shared Downstream Contract

`ComputeWiring<InputSource>` owns all four physical edge/source ports, finite
queues, source memories, Scatter/Gather/local merge, global merge, indexer,
Apply, degree port and acknowledged replica writer. `CompactSource` supplies
only reader creation, input payload initialization, task start and physical
input extent. The old public `Wiring` name remains an alias for this source.

The extraction preserves component construction/registration order, names,
clock, timings, capacities, memory placement and the independent task/drain
coordinator. Before editing, all eight current A4 executions are checked
against the frozen accepted matrix. After extraction, every complete result,
stdout, state, cycle, memory ledger and task lifecycle must match. UBSan also
reruns all three graph inputs. No cycle multiplier or new global barrier is
introduced. Future B must instantiate this same downstream with its input
source; copying a second version would weaken resource equivalence.

No CMake or SST source list changes apply: only optional test headers are
extracted, and the separate source probe is compiled by its guarded runner.
Production engine bodies and frozen plugins are unchanged.

## PMA And Source Boundary

Original-host DBG and A4 scheduling remain unchanged. Within each task,
destinations are made local to that task's 65,536-vertex partition, grouped
by source and sorted. Each nonempty source reserves a multiple of sixteen
32-bit slots. Unused slots have bit 31 set. Row bounds retain every source,
including empty rows. Four physical cache/DDR parity buffers match the HLS
adapter's segment selection; initialized duplicate copies are not an update
engine or a measured upload.

The control preserves edge multiplicity. This is a read-only PMA ABI control,
not original GraSU host construction or duplicate-edge update admission.
An original A4 task containing only dummy entries gets one empty reserved
segment at its original dummy source. That keeps its required termination
without adding a logical edge. Both compatibility conditions are explicit.

The source probe calls an unchanged hash-pinned copy of the HLS function.
It checks every AXIS data lane, keep/strb mask and TLAST, then records actual
packet payload. C++ independently compares the complete logical edge multiset
to original tasks; Python separately checks PMA bounds/compaction and all
recorded packets. Original task order, graph properties/degrees and logical
edges are not replaced by a smaller or deduplicated workload.

## Limits Before Finite B

The original adapter is called through unbounded HLS C-simulation streams
with immediate source memory. It is not timed inside the A4 finite model.
The captured edge stream is evidence, not a converted edge array used to
claim conversion-free performance. Source access counts do not determine
AXI burst coalescing, bundle arbitration or HBM service cycles.

This controlled PMA follows original A4 task assignment to isolate the input
change. It is not the routed K4 implementation's destination-shard ownership
or 23-channel placement. A finite B result must retain the declared matched
resource contract and report that distinction, extra metadata/PMA work,
backpressure and overlap. G publication timing and system C remain separate.

All current graph tasks fit the hot regions, and the four physical buffers
hold identical initialized copies. Cold routing and selection between
genuinely different current/stale copies remain dedicated stress gates;
these source results do not establish those behaviors.
