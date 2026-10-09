# Original GraSU Host Composition

This optional source control extends the prepared-PMA kernel checkpoint with
original trace-aware host preparation and host merge. Read the
[results and compatibility findings](../../experiments/comparisons/grasu_regraph_stage_validation/GRASU_HOST_INPUTS.md)
first. It is not a production G+R change, a finite-cycle model or a published
GraSU performance reproduction.

## Ownership

| Responsibility | Owner |
| --- | --- |
| Thin entry point | `scripts/run_original_grasu_host.py` |
| Fixed matrix, geometry and execution limits | `configs/experiments/original_grasu_host_v1.json` |
| Original-host compatibility patches | `configs/experiments/patches/grasu_host_*_bounds_v1.patch` |
| Trace generation and independent sequential-update admission | `spine_cycle_sim/experiments/upstream_controls/grasu/host/fixtures.py` |
| Clean source pin, isolated patch copies and compilation | `grasu/host/preparation.py` |
| Independent mapping/reservation/PMA state oracle | `grasu/host/layout.py` |
| Exact search request and dispatch-packet oracle | `grasu/host/protocol.py` |
| Captures, counters and diagnostic admission | `grasu/host/analysis.py` |
| Original bounds failures and corrupted-output rejection | `grasu/host/validation.py` |
| Fresh-build old G complete-state/protocol equivalence | `grasu/host/regression.py` |
| Bounded repeated and UBSan execution | `grasu/host/study.py` |
| Raw re-admission and immutable packaging | `grasu/host/delivery.py` |
| Original-host and original-kernel source composition | `cpp/tests/publication_sources/grasu_host_probe.cpp` |
| Input, layout, search and physical state checks | `cpp/tests/publication_sources/grasu_host/{input,layout,search,device}.hpp` |
| Focused independent tests | `tests/test_original_grasu_host.py` |

The nested host owner does not add modes to the earlier constructed-PMA
control. It reuses that control's generic search-memory observer and BIPA
replay helper, but does not execute its fixture builder or use its search
tables. Shared process limits and dependency hashing remain in the parent
`upstream_controls` package; there is no second subprocess launcher.

## Original And Compatibility Boundaries

The probe includes original `host.cpp` with its OpenCL main renamed. Its
original text loader, comparator and `merge_data` are called directly; its
OpenCL startup, DMA and event logic are not called. Real XRT/OpenCL headers
are used, and dead-code elimination removes the unused device main. The
host class uses one of three isolated copies: unchanged, row guard only,
or both reviewed bounds guards. The pinned author checkout remains clean.

The original class orders vertices by update frequency divided by the number
of reserved 16-slot segments. It maps source and destination IDs, reserves
the unique union of initial edges and future insertions, constructs search
heads before filtering future edges, then compacts initial live values inside
each segment. Equal priorities have unspecified sort order. Admission checks
the permutation and monotonic priority, not an invented tie ordering.

Author upload packing is inline in the unused main, so the wrapper reproduces
its parity split and cache/DDR copies explicitly. It additionally defines
all otherwise-uninitialized padding as the empty-slot value. That is a named
compatibility change, not execution of the original OpenCL upload block.

Original read/search/BIPA/merge/dispatch/cache/DDR function bodies are unchanged.
Memory callbacks return immediately and BIPA is checked by replay, as in the
[earlier kernel control](original_grasu_source_path.md). DDR pointers alias as
in original host code. Each of the four observed physical buffers is compared
against its complete slot oracle, including stale duplicate regions. Observed
buffers, not oracle values, are then passed to original `merge_data`. Every
merged slot and the restored external-ID edge set must agree independently.

## What Remains Unmodeled

Unbounded C-simulation streams and immediate memory do not establish finite
FIFO liveness, concurrent DATAFLOW behavior, DDR read-after-write timing,
memory contention or FPGA cycles. Loop-derived cache traffic is not measured
AXI bus traffic. CPU preparation cost and device launch are not benchmarked.
No CMake/SST source-list change applies because this is an optional runner-built
author-source probe, not a production engine component.

The next G owner must model these finite resources explicitly. It also needs
separate source16/paper8 geometry, original temporal-workload admission and the
publication event window. The A4/B adapter comparison and host/system C remain
separate gates; none can be inferred from this functional result.
