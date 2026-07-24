# Spine online carry target writer

Date: 2026-07-24

## Scope

This milestone replaces carry's post-merge bulk graph write with the online
target writer used by the current HLS. The source reference is
`afb8199a2ca8d3fd208b985324bf4d8719e2b839` on
`origin/reduce-levels-for-routing`, specifically
`partitioned_emit_target_group()` and
`partitioned_write_carry_target_family()` in `src/spine_partitioned.hpp`.

Before this change, the simulator consumed every k-way merge input into a host
vector, sorted/coalesced the complete vector, built complete CSR arrays, and
only then queued graph writes. Memory bytes were correct, but the writer could
not backpressure merge and its request order did not resemble HLS.

The host-side `carry_merge_inputs_` staging vector has been removed. The final
logical level vector remains only as a correctness/state mirror; it no longer
determines carry graph-write traffic.

## Online execution

The k-way merge now owns one current `(src,dst)` group. For every winning head:

1. equal keys accumulate signed differential and minimum weight;
2. a key transition emits the preceding non-zero group before refilling the
   winning input;
3. a zero differential group is counted and dropped without edge/index state;
4. each emitted group queues one 64-bit edge write through the finite graph
   AXI/HBM path;
5. writer-generated memory tasks block subsequent merge progress through the
   existing component scheduler and finite request queues.

The writer mirrors the HLS pending packers:

- row offsets: two `u32` values per graph word;
- destination partition masks: four `u16` values per graph word;
- page bases: two sparse `u32` values per graph word;
- source bitmap: four graph words flushed on page change/end;
- page list: four `u16` page IDs per metadata word;
- page epoch: one packed metadata-word update per newly entered page;
- edge payload: one graph word per emitted differential group.

Finalization writes the terminal row offset and terminal page-base sentinel,
then flushes row, mask, page-base, bitmap, and page-list packers in HLS order.
An empty result still writes the two terminal index words, matching the HLS
carry writer rather than silently doing no work.

## Counters

The result JSON now includes:

- groups seen, emitted, and cancelled;
- edge, row, mask, page-base, bitmap-page, page-list, and page-epoch writes;
- cycles with at least one writer task queued or in flight;
- maintenance start, end, and component-local cycle span.

`carry_refill_wait_cycles` remains the inclusive carry wait ledger. The new
`carry_writer_memory_wait_cycles` is its writer-attributable subset.

## Focused evidence

The one-page L1 test produces two groups and records:

| Item | Value |
| --- | ---: |
| Total maintenance cycles | 2,596 |
| Carry wait / writer subset | 118 / 18 |
| Edge words | 2 |
| Row / mask words | 1 / 1 |
| Page-base words | 2 |
| Bitmap pages | 1 |
| Page-list / epoch words | 1 / 1 |

HBM readback confirms bitmap bit 0 and row offsets `[0,2]`; the downstream
reader then emits both carried edges. This readback also protects a C++
evaluation-order bug found during implementation: payload length must be
captured before moving a bitmap byte vector into a memory task, or a nominal
32-byte write can become a zero-byte request.

The L2 k-way test emits eight groups across five source rows. It records three
row words, two mask words, two page-base words, eight edge writes, and 117
writer-wait cycles.

A five-page boundary test emits sources on pages 0 through 4. It records:

- five bitmap-page writes;
- three row words and two mask words;
- four sparse page-base words;
- two page-list words across the four-ID lane boundary;
- five page-epoch word writes;
- 232 graph-index bytes and 40 edge bytes.

Direct HBM readback verifies page-list words `{0,1,2,3}` and `{4}`. A signed
insert/delete cancellation test verifies one seen/cancelled group, zero edge
writes, and the two required terminal index writes.

## SST-HBM evidence

| Scenario | E2E cycles | Maintenance cycles | Backend requests | Result |
| --- | ---: | ---: | ---: | --- |
| Amazon L0 | 7,187 | 2,296 | 1,399 | exact |
| Carry + hot | 8,966 | 4,058 | 1,944 | exact |
| Weighted SSSP | 33,866 | 2,351 | 4,196 | exact |

The carry run has 1,230 DRAM reads, 714 writes, 96 activates, 14 writer-wait
cycles, and zero correctness/frontier mismatches. Its E2E cycles and backend
transactions equal the preceding payload-cursor milestone. This is expected:
the old 16-byte edge bulk was already split into two 8-byte transactions by the
source-shaped graph AXI, and later reader/compute work remains the E2E critical
path. The maintenance request ledger does change from 213 to 214 because it
now sees two explicit edge write requests instead of one parent request.

## Evidence tier and remaining boundary

This is `structural_execution_driven` evidence, not source-matched hardware
cycle calibration. It closes online carry output grouping, graph request shape,
pending-word packing, and merge/writer backpressure. Remaining boundaries are:

- the L0 writer still builds and queues complete payloads after its scan;
- carry cursor page/row reads are still batched rather than fully lazy;
- epoch wrap resets the epoch but does not yet execute the HLS full target-index
  clear loops;
- target/occupied-level selection starts from logical state;
- packed page-epoch updates use the initialized metadata mirror instead of an
  explicit read-modify-write transaction;
- malformed writer/cursor paths stop the simulator rather than emitting the
  complete HLS overflow/status transcript;
- packer/control operations use source-derived cycle structure but have no
  current-source csynth or hardware timestamp calibration.

The result supports writer request/byte studies, page/row packing sensitivity,
carry writer bottleneck attribution, and architecture what-ifs. It does not
yet justify absolute cycle-accuracy claims for all maintenance paths.

## Reproduction

```bash
cd /home/chuxiao/spine-cycle-sim

cmake --build build/cycle-core -j2
build/cycle-core/cpp/spine_cycle_core_tests spine_cold_l1_carry
build/cycle-core/cpp/spine_cycle_core_tests spine_carry_kway_refill
build/cycle-core/cpp/spine_cycle_core_tests spine_carry_writer_packer_boundaries
build/cycle-core/cpp/spine_cycle_core_tests spine_signed_diff_cancellation
ctest --test-dir build/cycle-core --output-on-failure
python3 -m unittest discover -s tests
make -C cpp/sst -j2

python3 scripts/run_sst_spine_vertical.py \
  --scenario carry_hot --no-build \
  --out-dir results/sst_spine_online_carry_writer_final_20260724
```

Machine-readable evidence is in
`docs/evidence/spine_online_carry_writer_20260724_summary.json`.
