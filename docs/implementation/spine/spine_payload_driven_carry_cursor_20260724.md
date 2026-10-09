# Spine payload-driven carry cursor

Date: 2026-07-24

## Scope

This milestone makes old-level source discovery in maintenance carry depend on
returned HBM payload rather than `SpineL0State`. The source reference is
`afb8199a2ca8d3fd208b985324bf4d8719e2b839` on
`origin/reduce-levels-for-routing`, specifically
`partitioned_carry_cursor_init/load_page/next/finish` in
`src/spine_partitioned.hpp`.

The previous request-driven carry engine already fetched old edge destination,
weight, and differential payload from HBM. It still copied source IDs from the
logical C++ level vector and issued index reads whose responses did not control
execution. That was an authority gap: changing the HBM bitmap could not change
the source entering the merge.

## Implemented payload chain

For every occupied lower-level stream, the simulator now executes this chain:

1. read the eight-word family/level slice metadata and decode edge count, row
   count, occupied flag, and graph offsets;
2. read packed slice epoch and page-list count metadata;
3. read and validate the packed, strictly increasing 16-bit page IDs;
4. for every listed page, read its packed page epoch, packed page-base entry,
   and four 64-bit source bitmap words;
5. reject stale epochs, non-contiguous page bases, invalid page IDs, and bitmap
   row-count mismatches;
6. reconstruct ordered source rows from returned bitmap bits;
7. read and validate row offsets, then expand each source row into one source
   ID per old edge;
8. issue one 64-bit old-edge head/lookahead read at a time using the returned
   edge offset and pair the payload with the reconstructed source;
9. feed those entries into the existing minimum-head differential merge.

The logical level vector is still used to decide which lower levels participate
and which binary target is selected. It is no longer the authority for old
source IDs, graph offsets, row ranges, or edge payloads once a cursor exists.

## Cursor execution cycles

The HLS `PARTITIONED_CURSOR_FIND_SOURCE` loop is pipelined at II=1. Across a
fully consumed page it performs:

- 256 bitmap-bit iterations;
- one page-load refill increment;
- three bitmap-word transitions;
- one page-finish iteration.

The simulator therefore accounts 261 base cursor refill cycles per visited
page, in addition to finite AXI/HBM response time. This is not a fitted
constant: it follows directly from the pinned HLS control loop and its
`refill_stalls` counter updates.

New counters expose the complete ledger:

- `carry_cursor_metadata_read_bytes`
- `carry_cursor_page_ids` and `carry_cursor_pages_visited`
- `carry_cursor_bitmap_words` and `carry_cursor_bits_inspected`
- `carry_cursor_refill_cycles`
- `carry_cursor_rows_entered` and `carry_cursor_row_offset_reads`
- `carry_cursor_validation_failures`

## Anti-bypass and error evidence

The focused anti-bypass test preloads logical state with old source 256, then
overwrites the HBM page-1 bitmap so that bit 44 selects source 300. It leaves
the row offsets and old edge payload valid. The carried L1 output contains the
new edge at source 256 and the old edge at source 300. This proves that the
source came from HBM cursor metadata rather than the logical level vector.

The same test records exactly 96 metadata bytes, one page ID, one visited page,
four bitmap words, 256 inspected bits, 261 refill cycles, one entered row, two
row-offset values, and zero validation failures.

A separate negative test overwrites page epoch with zero after preload. The
cursor rejects the stale HBM payload and increments `validation_failures`; it
does not fall back to host state.

## SST-HBM evidence

| Scenario | Cycles | Backend requests | Cursor pages | Cursor cycles | Result |
| --- | ---: | ---: | ---: | ---: | --- |
| Amazon L0 | 7,187 | 1,399 | 0 | 0 | exact |
| Carry + hot | 8,966 | 1,944 | 1 | 261 | exact |
| Weighted SSSP | 33,866 | 4,196 | 0 | 0 | exact |

All three runs report zero result and frontier mismatches. The carry run has
1,230 DRAM reads, 714 writes, 96 activates, and no backend submit or response
queue stalls.

The previous page-list milestone measured 8,736 cycles and 1,943 requests for
carry. Payload-driven cursor execution changes this to 8,966 and 1,944. The
230-cycle total increase is intentionally not equal to the 261-cycle cursor
ledger: replacing the old pre-issued index chain also changes request ordering
and overlap. The scheduler result, not addition of isolated counters, is the
end-to-end prediction.

## Evidence tier and remaining boundary

This milestone is `structural_execution_driven`, not hardware-cycle
calibrated. It closes old-source and old-edge payload authority and exposes the
HLS cursor's base loop work. It does not yet establish cycle-exact carry time:

- page epoch/base/bitmap requests are issued after the page list as a bounded
  batch, while HLS loads one page as `cursor_next()` reaches it;
- row-offset payload is fetched as one bounded request and expanded before
  merge, while HLS reads row boundaries on source discovery;
- cursor base cycles are serialized after its memory chain, preserving total
  work but not every possible memory/loop overlap;
- occupied lower-level selection and target selection still originate from
  logical state before payload validation;
- target bitmap/page-base/row-offset/edge writes are still assembled after the
  complete merge rather than emitted with merge groups;
- no source-matched hardware timestamp or current carry csynth latency has
  calibrated this path.

The result is suitable for source-authoritative correctness, request/byte
traffic, page-density sensitivity, and structural bottleneck experiments. It
is not yet evidence for absolute cycle accuracy of carry-heavy workloads.

## Reproduction

```bash
cd /home/chuxiao/spine-cycle-sim

cmake --build build/cycle-core -j2
build/cycle-core/cpp/spine_cycle_core_tests spine_carry_hbm_level_payload
build/cycle-core/cpp/spine_cycle_core_tests spine_carry_stale_page_epoch
build/cycle-core/cpp/spine_cycle_core_tests spine_cold_l1_carry
build/cycle-core/cpp/spine_cycle_core_tests spine_carry_kway_refill
ctest --test-dir build/cycle-core --output-on-failure
python3 -m unittest discover -s tests
make -C cpp/sst -j2

python3 scripts/run_sst_spine_vertical.py \
  --scenario carry_hot --no-build \
  --out-dir results/sst_spine_payload_cursor_carry_20260724
```

Machine-readable evidence is in
`docs/evidence/spine_payload_driven_carry_cursor_20260724_summary.json`.
