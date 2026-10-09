# Original Big Memory And Scatter

The isolated original-R library now has separately owned Big source request,
cache-wrapper, response-router and Scatter components. These are not modes
inside Little or timing factors applied to the ported G+R. The
[study checkpoint](../../experiments/comparisons/grasu_regraph_stage_validation/BIG_MEMORY_FRONTEND.md)
owns the fixed matrix, raw evidence and remaining boundaries.

## Ownership

| Responsibility | Header / source |
| --- | --- |
| Cacheline batch, request, response and per-lane payload types | `original_regraph/big_frontend_types.hpp` |
| Edge/source fork, request-batch generator and serial sender | `big_requests.hpp` / `big_requests.cpp` |
| Finite original last-cacheline source service | `big_source_memory.hpp` / `big_source_memory.cpp` |
| Initial broadcast, lane response routing and PR Scatter | `big_scatter.hpp` / `big_scatter.cpp` |
| Fixture/independent request and value oracles | `cpp/tests/original_regraph/big_frontend_fixture.hpp` |
| Finite memory/port/stream wiring | `big_frontend_wiring.hpp` |
| Execution, nonintrusive observation and ledgers | `big_frontend_execution.hpp` |
| Matrix and original-source comparison executables | `big_frontend_tests.cpp`, `big_frontend_comparison.cpp` |
| Independent author-function capture | `cpp/tests/publication_sources/regraph_big_frontend_probe.cpp` |

The existing `LittleEdgeReader` is deliberately reused without edits: both
author tops have the same 512-bit edge decode, destination-offset subtraction
and dummy/local-19-bit conversion. This does not reuse Little Scatter's
source-window protocol. A separate registered fork decouples edge processing
from the source-request generator.

## Request And Property Protocol

The generator masks source flag bit 31 and admits sorted source IDs below
`2^30`, the author's 26-bit cacheline-address domain. It tracks the previous
packet's maximum source line, initially zero. If the current maximum changes,
it requests every lane after the prefix reusing that previous maximum.
Duplicate lines within a packet remain duplicate lane requests. The serial
sender first requests line zero unconditionally, then emits each requested
lane, and finally one end token. It does not replace this with one window
read or deduplicate the lane stream.

The original wrapper caches only its last requested cacheline. A new line
causes one 64-byte read; consecutive requests for that same line reuse its
data but still emit one response each. The finite model retains pending read
results with a bounded ordered-response queue, allowing same-line followers
to reference the pending result rather than issue duplicate reads. This is
not a general associative source cache. The end token invalidates it, and
each new partition again reads line zero.

The first response is broadcast to all eight lane queues. Subsequent
responses go only to their tagged lane. Scatter keeps the last packet's
maximum cacheline, reuses it where possible and otherwise consumes that
lane's response. After each packet all lane caches conceptually adopt the
last lane's cacheline, as in the author function. Model response metadata
also records the requested line to check address/response alignment; the
original wire carries only the lane and data.

The selected PR preprocessing forwards the source property. Zero values and
dummy edges still pass through Scatter. Dummy filtering belongs to Gather.
Destination IDs above 65,535 and nonzero partition offsets are included in
the controls; using the shared edge decoder does not truncate Big to Little's
65,536-destination Gather capacity.

## Resource And Timing Boundary

The baseline uses edge/source channels 22/23 of a 32-channel mock backend,
64-cycle latency, one 64-byte beat per channel per cycle and sixteen AXI
outstanding bursts. Edge requests have two parent credits; single-line source
reads have sixteen. The wrapper has an explicitly assumed 32 live request
slots. Its cache register, pending read storage and per-lane queues are
different resources and have separate ledgers.

Named source-stream depths follow the author top: edge 32, source-ID 16,
request batches 32, cacheline request/response 32, each property lane 32 and
updates 16. The extra shared-reader output and external AXI queues are finite
model boundaries. A depth-one control constrains all queues. The shared edge
pipe `(latency, II, capacity)` is `(3,1,4)`, Scatter `(4,1,5)`. The fork,
batch generator and serial sender use registered transaction reservations.

These are cycle predictions, not exact HLS global-stall/partial-write timing.
The wrapper's live-slot assumption and uniform mock-memory service are not
recovered routed measurements. Original HLS may coalesce reads; this model
issues one AXI line per last-cacheline miss. Actual original-publication
memory, clock, graph-selected topology and event admission remain required.

The execution window begins with resident compact edges and properties and
ends when every edge, source request, lane value, update, AXI acknowledgement
and backend operation drains. It excludes Gather, mixed Little/Big scheduling,
Apply/writeback, host preparation, launch and readback. Author C-simulation
and model UB checks are separate from measured FPGA timing.
