# Original A4 Graph Execution

The independent `original_regraph_cycle` components now execute every
scheduled task of the [admitted author-host inputs](original_regraph_inputs.md).
The [whole-graph study](../../experiments/comparisons/grasu_regraph_stage_validation/A4_GRAPH_EXECUTION.md)
owns results and reproduction. Production G+R, Spine and SST numerical bodies
are unchanged; this remains an isolated optional CMake validation executable.

## Ownership

| Responsibility | Owner |
| --- | --- |
| Bounded binary loading, task geometry and independent CSR sum/PR reference | `cpp/tests/original_regraph/whole_graph/input.hpp` |
| Finite components, physical memory placement and independent per-kernel task progress | `whole_graph/wiring.hpp` |
| Resident execution, nonintrusive pre-Apply observation, replica/guard checks and result emission | `whole_graph/a4_execution.cpp` |
| Shared finite memory/AXI test ownership | `cpp/tests/original_regraph/memory_fixture.hpp` |
| Fixed experiment preparation/execution/admission and delivery | [original_regraph_execution](../../../spine_cycle_sim/experiments/original_regraph_execution/README.md) |

The new wiring intentionally does not call synthetic fixture initialization
or the old state's guard-filling `begin`: whole-graph properties and degrees
come from the author's captured preparation, and live buffers must not alias.
The shared reader/source/Scatter/Gather/merge/Apply/writer implementations
remain the same finite components used in previous source comparisons.

## Input And Functional Window

`execution.u32le` is a little-endian 32-bit-word interface, not a handwritten
JSON parser. Its eight header words are magic `0x3447524f`, version one, V,
logical E, padded V, published V, task count and partition count. Each task has
eight words: partition, subpartition, kernel, destination offset, destination
extent, edge-word offset, edge-word count and reserved zero. All descriptors
must follow the original dense ordering and odd-partition reversal. Five
unchanged captures supply tasks, initial properties, degrees and reordered CSR.
The Python admission gate checks them against the delivered author-host hashes.
Fresh output paths are allowed, but source revisions, preparation code,
complete task descriptors and all seven captured data identities must match
the accepted checkpoint. Regenerated original Gather/Apply controls pass their
existing strict source-admission gates and retain frozen numerical hashes.

Each kernel has one task per nonempty destination partition. Its next task
starts after its own reader, Scatter, Gather, local merger, streams and AXI
ports drain. It does not wait for other kernels or acknowledged publication
of the previous partition. Continuous global merge/index/Apply/writeback can
overlap the next task. The coordinator records every start/completion edge.

The measured model window starts with resident inputs and the first tasks,
then ends only after all tasks, streams and write acknowledgements drain.
Graph upload, DBG/partitioning, degree/property initialization, host enqueue,
launch/relaunch and readback are outside it. No warm/cold system speedup or
host-inclusive performance is inferred from this static PR control.

There is one original-style fixed PR iteration with argument zero. Before
each scheduler step, the observer snapshots the global-output head; it checks
that value only if the existing indexer consumes it. It inserts no FIFO,
pipeline delay or backpressure. Every published pre-Apply sum is checked
against the independent complete CSR traversal. All four output replicas are
then checked against the original signed-domain PR formula, including padded
vertices and allocation guards. Captures contain actual inspected device
payload, not host-computed reference output.

Only the nonempty destination prefix is written, as in the original wrapper.
The skewed case has a larger padded source extent than this prefix; its
unwritten output tail is initialized to zero and checked against the full
first-iteration reference. Multiple full-graph iterations or convergence are
not claimed. Previous tiny resident-round tests remain a separate boundary.

## Memory And Resources

| Resource | Whole-A4 configuration |
| --- | --- |
| Little pipelines / Big pipelines | 4 / 0 |
| Gather per Little | Eight private 65,536-value arrays; logical 2 MiB |
| Source buffers per Little | Eight replicas of two 4,096-property windows; logical 256 KiB |
| Global output rate | One merged vertex pair per cycle, eight pairs per 512-bit line |
| Stream queues | Registered depth 8 |
| Clock / mock memory | 210 MHz / 32 channels, 64-cycle baseline latency, one 64-byte beat per channel per cycle |
| Edge channels / source-and-writer channels | 0/2/4/6 and 1/3/5/7 |
| Degree channel | 30 |
| AXI burst/outstanding limits | 16 beats / 16 bursts per master |
| Edge/source parent-request limits | 2; each large parent can split into many bursts |
| Degree/writer parent-request limits | 16; requests are single 64-byte lines |
| Apply live lines / writer retained lines | 100 / 72 |
| Source / output addresses per property channel | 0 / 64 MiB; nonoverlapping complete padded extents |

The instantiated HLS top modules resolve 512-bit ports and sixteen read/write
outstanding capacities. Generic AXI submodule defaults of two are not the
instantiated settings. The new resource-evidence owner verifies symbolic data
widths and instance overrides against the accepted synthesis reports, storing
file hashes and resolved parameters.

The old memory fixture's `max_pending_requests=2` limited single-line degree
and write concurrency even though its burst limit was sixteen. Optional parent
credits now make that limit explicit; every existing caller still defaults to
two. Full old component and original-source comparison outputs stay byte-identical.
The new sixteen-parent whole-graph path is a declared configuration, not a
timing multiplier or a rewrite of frozen component results.

This is still a mock controller. Source reads and writes use separate logical
AXI masters sharing one physical channel; HLS `gmem` bundle arbitration,
automatic coalescing and global-stall behavior are not cycle-exact. Uniform
depth-eight streams and the existing finite elastic pipes are declared model
assumptions. The 64-cycle latency is not an observed HBM latency. Original
publication-speed matching requires memory/topology/window admission rather
than treating these functional results as calibration.
