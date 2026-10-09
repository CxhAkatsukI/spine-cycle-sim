# Original ReGraph Input Preparation

This optional source-control probe executes the author's graph loader, DBG
reordering, destination partitioning, task scheduling and PR initialization.
It is separate from `original_regraph_cycle`, production G+R and the SST
plugin. The [fixed study](../../experiments/comparisons/grasu_regraph_stage_validation/ORIGINAL_HOST_INPUTS.md)
owns its evidence and reproduction commands.

## Review Order

1. `configs/experiments/original_regraph_inputs_v1.json` declares all inputs,
   topologies, seed, capacity limits and excluded claims.
2. `cpp/tests/publication_sources/regraph_layout_probe.cpp` invokes unmodified
   original `.cpp` functions from a fresh generated source tree.
3. `regraph_layout_support.hpp` reconstructs the DBG permutation and checks
   every reordered edge and source outdegree against the pre-reorder CSR.
4. `regraph_layout_validation.hpp` checks initialization, every scheduled
   logical edge, padding, source windows and memory/arithmetic bounds.
5. `regraph_layout_capture.hpp` emits explicit descriptors and seven binary
   captures; Python validates metadata, extents and repeated hashes.
6. The [Python owner](../../../spine_cycle_sim/experiments/original_regraph_inputs/README.md)
   separates preparation, execution, analysis, instrumentation and delivery.

## Original Behavior Kept Intact

The source loader expects two integer columns without a header and keeps
integer IDs: `V = max_id + 1`. Duplicate edges remain duplicate edges. A path
containing `ungraph` selects the author's undirected loader, so this directed
matrix rejects such paths before calling it. A `.mtx` extension does not imply
a Matrix Market header; the pinned Amazon artifact is a raw two-column file.

DBG first sorts by indegree, then shuffles within the original buckets. The
probe pins the environment's `time()` input to seed 73, since the original
function calls `srand(time(0))`. It does not replace the author's reordering
body. Compiler, library-header hashes and the graph permutation are recorded;
equal seeds alone do not promise cross-toolchain shuffle identity.

The upstream CSR destructor is declared but not defined. A default destructor
is supplied by the probe for linking; no graph algorithm is changed. Real
OpenCL/XRT headers and `libOpenCL` supply author-host types. No fake device API,
kernel launch, upload or `transferPartitions` timing is used. Linker section
garbage collection removes unused device-transfer functions.

Destination partitions contain 65,536 vertices. Little source windows contain
4,096 vertices and each edge packet contains eight `(source,destination)`
pairs. Original final padding always adds between one and eight dummy edges,
including eight when already aligned. Empty scheduled lanes receive dummy
packets. The oracle excludes canonical `0xffffffff` destinations from logical
work but preserves every physical edge and original source termination flag
in the capture. Odd partitions reverse the original kernel assignment.

For four Little and zero Big, the author scheduler makes every nonempty
partition dense. For the 11-Little/3-Big example, the declared manual argument
selects one dense partition and merges the remainder into eight-partition Big
groups. This is an author-artifact example, not the unknown graph-selected
best topology used for a particular published throughput row.

## Capture Interface

All words are unsigned 32-bit little-endian; signed source properties retain
their original bits. JSON descriptors give word offsets, word counts,
destination ranges and task/kernel assignment.

| File | Word sequence |
| --- | --- |
| `original_to_reordered.u32le` | One old-to-new vertex ID per original vertex |
| `csr_offsets.u32le` | Reordered CSR offsets, `V+1` words |
| `csr_destinations.u32le` | Reordered CSR destinations, `E` words |
| `initial.u32le` | Original PR properties, padded vertex extent |
| `degrees.u32le` | Original outdegrees, padded vertex extent |
| `partitions.u32le` | Concatenated original partition edge words |
| `tasks.u32le` | Concatenated dense then sparse scheduled task edge words |

The C++ oracle compares the full scheduled logical-edge multiset with CSR,
including duplicates, and checks each mapped original CSR edge. It verifies
the author's `int(float(1/V) * 2^30) / degree` initialization. Its safe 64-bit
first-iteration sum check rejects cases outside original signed-32-bit
Gather/Apply arithmetic. This is only an initial-iteration domain check, not
a proof that arbitrary subsequent PR iterations cannot overflow.

Every Little task checks the source lookahead allocation, packet/window
alignment and source/destination bounds. Total scheduled edge bytes per kernel
and the property plane must fit a 256-MiB channel. These fixed inputs pass;
arbitrary graphs with gaps in nonempty destination partitions are not admitted
because the author scheduler assumes a contiguous nonempty prefix.

## Timing Boundary And Next Gate

Observed CPU time includes loading, original preparation, independent full-edge
validation and capture I/O. It is not original host-preprocessing performance,
an accelerator kernel window, or a publication-speed match. Large binary
captures stay under ignored `results/`; all hashes and extents are delivered.

Before whole-A4 timing, audit the existing test memory fixture's parent-request
credits. It currently allows two parent requests and sixteen bursts. Large
edge/source parents split into bursts; single-line degree/write parents do
not. Thus those ports can have only two live requests despite a sixteen-burst
limit. A new whole-path configuration must derive per-port parent credits
from original AXI evidence and preserve the existing default and frozen
component regressions. Do not hide this difference in a timing multiplier.
