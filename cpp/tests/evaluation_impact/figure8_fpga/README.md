# Fig8 Persistent FPGA Hosts

Standalone real-FPGA update-only wrappers, not simulator timing paths. Both reuse
pinned production hosts with `main` renamed, bootstrap once, and retain the
device graph across one measured pass without propagation or repetitions.
See [BUILD.md](BUILD.md) for dependency-based portable source and build notes.

## Sources And Interfaces

| Wrapper | Local implementation | Retained production source |
| --- | --- | --- |
| Spine | [spine_persistent.cpp](spine_persistent.cpp), [bridge](spine_setup_once_bridge.hpp), [input](spine_persistent_input.hpp) | `spine-hls-fig8-native`, revision `475edcacc2c8e482bd497515e31e370084af78f6`, `tests/test_integration/host_partitioned_algorithms_smoke.cpp` |
| G (GraSU only) | [gr_persistent.cpp](gr_persistent.cpp), [runtime](gr_persistent_runtime.hpp) | `grasu-regraph-fig8-g-once`, revision `81cbe8fa597315c829ae50ac3905d0365788ee60`, `tools/sharded_k4_native_host.cpp` |

The source roots are `/data/chuxiao/worktrees/spine-hls-fig8-native` and
`/data/chuxiao/worktrees/grasu-regraph-fig8-g-once`. Exact external file hashes
are in [spine_source_pins.sha256](spine_source_pins.sha256) and
[gr_source_pins.sha256](gr_source_pins.sha256). Spine uses the November 4
setup-once implementation, not the older October 25 resident host binary.
The pinned host has maintenance-only allocation/residency repairs: `active_bins`
retains a valid ABI buffer but not the unused 512-MiB propagation spool. The
bridge opts into deferred graph residency; the default resident-compute
constructor path is unchanged. The committed production-host repair is
`a72ecff` on `codex/fig8-native-spine-once` in the Spine HLS repository;
the file hashes, rather than the earlier base revision alone, bind this build.
Its bridge resets invocation bookkeeping only, never resident graph, metadata,
family-directory, or dirty-generation contents. G retains its PMA and buffers.

```text
spine_persistent.host <xclbin> --persistent-update --dynamic-graph <native.graph> --batches <B>
gr_persistent --persistent-update <xclbin> <native.graph> <B> <oracle.txt>
```

`--help` does not enumerate devices. Native input starts with `V E U`, followed
by E initial `src dst weight` records and U `src dst weight type` updates.
These wrappers accept new-edge insertions only, not deletions or replacements.
For U updates, batch i is the chronological file-order interval
`[floor(i*U/B), floor((i+1)*U/B))`, with `1 <= B <= U`; Spine sorts only after
forming that window. The requested matrix is 4096 total updates in ten batches
on AU/SU/WK/SO/PK, plus AU 131072 total in 10/100/1000 batches.
Each logical batch is split chronologically into physical invocations of at
most 8192 updates, before sorting. This bounds a single-family L0 output by
8192 and the first L1 merge by 16384, rather than overflowing L1 with two
13107-update batches. Every physical invocation's packing, DMA, launch and
completion are charged to the same logical batch. `physical_launches` records
the exact count. Capacity or oracle failures must remain failures.

G defaults to four metadata replicas; `GRASU_SHARDED_METADATA_REPLICAS=1` is an
explicit shared-table control, with no automatic fallback. Its initial PMA
reservation/placement uses the full trace; future update payloads are not
uploaded early. Record this trace-aware capacity policy with every result.

## Timing And Correctness

Per-batch `SPINE_PERSISTENT_BATCH` / `GRASU_PERSISTENT_BATCH` records use
zero-based `batch`, `updates`, `batch_ns` (selection, packing/preparation and
input DMA through completion), and `update_wall_ns` (launch through update
completion, including waits). G also splits preparation and upload. Summary
`batch_ns` and `update_wall_ns` are exact sums of those per-batch fields.

| Summary phase | Spine | G |
| --- | --- | --- |
| `layout_ns` | Initial host classification, planning, serialization and allocations | Initial PMA/metadata planning, replicas and static packing |
| One-time device setup | `bootstrap_ns`: host/buffer allocations, initial residency DMA and lifecycle initialization | `upload_ns`: buffer allocations, initial graph/metadata DMA and premigration |
| `setup_inclusive_ns` | `layout_ns + bootstrap_ns + batch_ns + update_wall_ns` | `layout_ns + upload_ns + batch_ns + update_wall_ns` |

Input parsing, device discovery, context/queue creation, xclbin reading and
programming, kernel-handle creation, final readback/oracle, logging and teardown
are outside these sums. They are selected-phase sums, not process wall time.
Spine's per-batch maintenance status readback/validation is also excluded.
**Exception:** initial lifecycle status readback and its validation are inside
Spine `bootstrap_ns`; the current help's general readback exclusion is broader
than this actual boundary. The production constructor starts its setup timer
after programming and kernel-handle creation, before buffer allocation, and
ends it after `initialize_vertex_domain(false)`. Its
`SPINE_UPDATE_SETUP_BOOTSTRAP` record splits host, migrate and lifecycle time.
Layout-array allocation is already charged in `layout_ns`, not omitted.

Final validation is mandatory before summary `status=PASS`: Spine checks the
complete graph against all initial edges plus all inserts; G replays the full
trace and compares every word in all trace-touched PMA segments (not a complete
untouched-PMA scan), requiring zero mismatches. Neither validates propagation.

## Bootstrap Policy And Execution

The repaired host places the static initial graph at **L10**, leaving L0--L9
for chronological updates. This is an explicit change from the failed V1
host's L2 configuration, not a kernel change or a timing-boundary change.
The current matrix uses at most 1000 physical invocations, below the 1024
nonempty family commits required to carry into the static L10 slice.
All classification, serialization and initial device residency remain timed.
This configuration has finite update headroom; it is not a claim that an
arbitrarily long run can avoid merging the static graph.

The older selected
[simulator L4 cohort](../../../../docs/experiments/comparisons/grasu_regraph_stage_validation/evaluation_impact/figure7_11_preview_20261105/fresh_simulator/portable_fig8_headroom_v1/README.md)
is not bootstrap-parity evidence for this host. The new wrapper builds compact
live payloads and initializes the family directory from those host payloads.
It allocates the fixed device arenas directly and uploads live regions once,
not an intermediate compact device image or empty address padding. Metadata
offsets are patched before the fixed image is used. Allocation, patching and
DMA remain timed. `graph_uploads=1`, `arena_allocate_ns` and `live_upload_ns`
identify this path in raw logs; the historical `relocation_ns` field is their
sum, not evidence of a second graph upload.
Arena bounds include both initial live regions and every target reachable
under the physical-launch budget; total edge count alone is not a valid bound
on the highest carry level. CPU layout tests cover the address mapping and
binary carry bounds before board execution.

The maintenance-only scratch upload initializes every read-before-write word
for the fixed vertex domain V: `ceil(V/128)` 128-bit dirty bitmap words are
zeroed and `ceil(V/4)` family-directory words contain the old graph's family
masks, including zeros for initially absent sources. Their fixed word offsets
are unchanged. Dirty-list valid lanes and family buckets are written before
consumption; padding lanes outside the published count are not inputs.
Owner state is initialized by the existing lifecycle kernel, which writes
its valid bitmap regions and control words without reading old device data.
The full scratch and owner device allocations remain present. Per-launch
input writes, metadata initialization, prefix DMA, lifecycle and waits are
still charged. `SPINE_MAINT_SPARSE_INIT` records both prefix sizes and
`owner_host_upload=0`. This optimization is restricted to maintenance setup;
it does not permit later vertex-domain expansion or propagation to consume
uninitialized scratch. See the delivered repair notes for the frozen kernel
read/write source locations.

The current maintenance-only path uses CPU staging for the update input and
the two initialized prefixes, not a zeroed full scratch/owner shadow. Device
allocations still use the full compiled scratch/owner sizes, independently of
the CPU vector lengths. Scratch, owner and graph arenas have explicit aligned
host backing allocated without full-array zeroing. Initial device residency uses
`CONTENT_UNDEFINED`, never a transfer of uninitialized host contents. Required
prefix writes and lifecycle initialization follow before any consumer. Patched,
initialized metadata is host-bound and migrated once, after fixed graph
placement; lifecycle has no metadata argument. `host_bound_scratch=1`,
`metadata_uploads=1`, `compact_host_staging=1` and
`uninitialized_host_backing=1` identify this implementation. The backing outlives
the OpenCL buffers. These flags do not remove required initialization or timing.

Board execution belongs to the bounded, lease-owning runner. Both require
`ORIGINAL_R_LEASE_FD` and `XCL_DEVICE_INDEX`, plus `SPINE_EXPECT_BDF` or
`GRASU_REGRAPH_EXPECT_BDF`. G additionally requires `GRASU_UPDATE_REPEATS=1`,
initial premigration enabled, and resident-compute mode unset. Compilation and
help are not hardware correctness evidence. A management/download timeout
before bootstrap is a programming/infrastructure failure, not an update run.

## V1 Hardware Outcome And Limits

The November 7 board0 run attempted all eight cases: four Spine points passed
the mandatory final oracle (AU/SU/WK/SO, 4096 updates in ten batches); four
failed. Keep all failures in the delivered matrix, without completed latency
or speedup values for those points. Raw receipts are under
`/data/chuxiao/checks/fig8-fpga-persistent-20261107-v1/board0`.

| Failed Spine case | Observed result |
| --- | --- |
| PK, 4096 / 10 | Maintenance overflow at batch 3 after successful targets L0, L1, L0. Exhausted bootstrap carry headroom is consistent with this sequence, but the generic overflow flag does not identify its exact cause. |
| AU, 131072 / 10 | Maintenance overflow at batch 1. Its two cold-family-0 batches contain 26214 inserts, exceeding the kernel's fixed L1 per-family capacity of 16384. Bootstrap L4 does not enlarge that target. |
| AU, 131072 / 100 | Maintenance overflow at batch 63. The retained result does not identify the exact overflow branch. |
| AU, 131072 / 1000 | All 1000 maintenance batches completed; mandatory final validation failed with `vector::_M_range_check`, index 17829908 versus size 3694361. This is not a maintenance-overflow result. |

The AU / 1000 index is exactly the kernel's fixed L10 bitmap base, in uint64
words. This establishes a concrete host allocation/layout mismatch, not proof
that device contents are otherwise correct. In the retained production source,
`host_split.hpp:2951` serializes compact initial slices, and
`host_partitioned_algorithms_smoke.cpp:563` allocates graph buffers using those
vector sizes. The frozen kernel's `source/src/spine_partitioned.hpp:3873`
defines fixed level offsets; its carry writer at line 5128 uses those offsets.
Thus a valid fixed-layout address can exceed the compact host allocation.
Simply resizing vectors is not a verified repair: fixed carry destinations
can also overlap still-live compact initial slices.

These are retained V1 outcomes, not results of the repaired host. L4 bootstrap
alone addresses neither fixed L1 capacity nor compact/fixed-layout
compatibility. The repair addresses layout, physical invocation size and
bootstrap headroom separately. The V1 executable, source archive and results
remain frozen; repaired runs use fresh build/output directories and a separate
delivery folder. A successful build is not a substitute for the final oracle.
