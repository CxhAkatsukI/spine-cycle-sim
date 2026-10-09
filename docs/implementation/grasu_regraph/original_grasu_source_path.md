# Original GraSU Source Path

This optional control executes pinned original-source functions, not the
production direct-cache G+R port or a new cycle model. Start with the
[study report](../../experiments/comparisons/grasu_regraph_stage_validation/GRASU_SOURCE_PATH.md)
for results and limits. The paper and frozen simulator/plugin are unchanged.

## Ownership

| Responsibility | Owner |
| --- | --- |
| Thin CLI | `scripts/run_original_grasu_source_path.py` |
| Fixed geometry and matrix | `configs/experiments/original_grasu_source_path_v1.json` |
| Bounded compile/run and repeated/instrumented admission | `spine_cycle_sim/experiments/upstream_controls/grasu/study.py` |
| Source pin, dependencies, old archive and preservation checks | `grasu/preparation.py` |
| Independent fixtures and final-state oracle | `grasu/fixtures.py` |
| Strict protocol, complete merged state and diagnostic checks | `grasu/analysis.py` |
| Re-admission and immutable raw archive | `grasu/delivery.py` |
| Original-source calls and capture | `cpp/tests/publication_sources/grasu_path_probe.cpp` |
| Fixed PMA, search-memory observation and update/state checks | `cpp/tests/publication_sources/grasu_path/{fixture,lookup,update}.hpp` |
| Rejection and boundary tests | `tests/test_original_grasu_source_path.py` |

The C++ helpers are separate because fixture construction, memory protocol,
and state transformation are different review responsibilities. The probe
does not contain a second PMA implementation or a timing multiplier. Namespace
wrappers avoid the duplicate upstream helper names `process` and
`dispatch_update`; they do not edit any author function body.

## Source Composition

Each batch follows the original host's four-way round-robin input split.
Within each search kernel, `read_edges` distributes updates over 64 lanes.
The original `binary_search` requests one row-offset entry then binary-table
entries, and emits its original 96-bit packet. Test-only request delegates
return the addressed immutable table value and record every address/value.

Every lane's recorded request stream is subsequently replayed through the
original 16-lane `bipa` helper; every response and end marker is consumed and
checked. This is functional decomposition, not a concurrent invocation of
top-level `bin_search` or its finite DATAFLOW channels. It does not measure
polling delay, FIFO capacity or memory response timing.

Original `merge_updates` restores each search kernel's order. Original
`dispatch` consumes the four kernel streams round-robin and emits updates to
the two cache and two DDR paths. Each bucket is observed for exact ordering
before being given unchanged to original `process_cache` or `process_ddr`.
DDR input/output pointers alias the same buffer, as in author `host.cpp`.

The four device buffers are distinct: even-half cache/DDR and odd-half
cache/DDR. Their cold/hot duplicate regions must remain stale where that
buffer is not the selected update owner. The C++ sorted-set oracle checks
every slot of every buffer after every batch, including untouched regions.
The final capture selects the cache owner below the hot threshold and the
DDR owner above it. Python checks every resulting slot independently.

## Fixture Boundary

`G-source16` has 16 32-bit slots per 512-bit segment, 131,072 cache segments
per half and 16 cache banks per half. The fixture allocates another 32 cold
segments per half, so both cache-boundary sides and every DDR routing lane
are exercised. It includes first/last hot bank rows, all cold routing lanes,
uneven update counts, all 256 search lanes, empty input and three batches.

This is a constructed, already-reserved kernel-ABI PMA. Its table layout is
not the result of running original trace-aware host preparation on a real
publication graph. In particular, the two source ranges deliberately span
the cache threshold. State/reservation capacity remains fixed across batches;
all insertions are absent and have space, and every deletion is present.
Duplicate inserts, absent deletes and rebalance are not admitted semantics.
The current fixtures exercise three-to-five live entries per segment, not
empty/full segment occupancy. An empty batch only checks unchanged state.

## Evidence Limits

C-simulation streams are unbounded and source memory accesses are immediate.
Sequential C-simulation does not establish concurrent DATAFLOW liveness or
DDR read-after-write safety across aliased AXI bundles. Those require separate
finite-resource or hardware controls, especially for repeated segment updates.

The exact upstream width-warning pair for `512-bit |= 32-bit` is retained and
counted once per valid insertion. Any missing, extra, different warning,
empty-stream diagnostic or UBSan report fails admission. Source bodies and
HLS headers are not patched to suppress the warning.

Byte counts are logical source accesses or loop-derived traffic, not measured
bus bursts. The cache performs full preload/writeback even for an empty batch.
Device cycles and publication error are deliberately null. `G-paper8`, original
host preparation, temporal workload identity, published event-window admission,
and finite-resource G timing remain separate work.

No CMake or SST source-list change is applicable: this optional author-source
probe is compiled by the bounded Python runner and adds no production engine
source or mandatory Vitis dependency. The earlier exact SST/Spine regression
is preserved; its full matrix is not rerun by this control.
