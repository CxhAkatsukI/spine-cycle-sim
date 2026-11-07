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
Spine checks the largest batch, not total U, against `MAX_SORT_N` (131072 in
the pinned image/build). Capacity or oracle failures must remain failures.

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

Spine currently hard-codes minimum bootstrap level **L2**. The older selected
[simulator L4 cohort](../../../../docs/experiments/comparisons/grasu_regraph_stage_validation/evaluation_impact/figure7_11_preview_20261105/fresh_simulator/portable_fig8_headroom_v1/README.md)
leaves lower levels free for carry headroom; it is not bootstrap-parity evidence
for this host (and uses a shared-metadata G control). The older simulator L2 PK
case exhausted a capacity-safe target at batch index 3. No L4 change is made
here. A future host-only preload option could retain the kernel ABI, but must
change classifier capacity, planner minimum and assignment bounds together and
revalidate capacity/correctness; there is no current CLI option.

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

There is no established low-risk, one-option host fix for all four failures.
L4 bootstrap alone addresses neither fixed L1 capacity nor compact/fixed-layout
compatibility. No L4 option, v2 binary, kernel change, or speculative source fix
was made for this diagnosis; the v1 executable sources and build remain frozen.
