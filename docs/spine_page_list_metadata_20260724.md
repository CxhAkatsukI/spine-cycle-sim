# Spine page-list metadata lifecycle

Date: 2026-07-24

## Scope

The current `reduce-levels-for-routing` HLS carry cursor discovers occupied
source pages through two persistent metadata regions:

- one packed 32-bit page-list count per family/level slice;
- packed 16-bit page IDs, four IDs per 64-bit metadata word.

The simulator already exposed these addresses in `SpineMetadataLayout`, but it
did not initialize or commit their payload. Logical C++ level vectors therefore
looked valid while the HBM ABI visible to a source-faithful carry cursor was
empty. This milestone closes that persistent metadata lifecycle against source
revision `afb8199a2ca8d3fd208b985324bf4d8719e2b839`.

## Implemented behavior

For every preloaded non-empty slice, maintenance initialization now:

1. derives the ascending unique source-page IDs;
2. writes packed page IDs at `page_list_base + slice * words_per_slice`;
3. records the count in the correct low/high 32-bit lane of the shared count
   word;
4. preserves the adjacent slice's lane when both slices share a word.

For every newly written target slice, maintenance now queues the page-ID
payload through the finite metadata AXI/HBM port. At commit it publishes packed
count words for all touched slices, sets the target count, and clears counts for
retired lower levels. Stale page-ID payload may remain below a zero count, as in
the HLS ABI; the count is authoritative.

Two explicit byte counters separate this traffic from graph index and edge
payload writes:

- `page_list_payload_write_bytes`
- `page_list_count_write_bytes`

An implementation bug found by the readback test is also covered: the page-list
payload length must be captured before moving its byte vector into the memory
task. Otherwise C++ argument evaluation may move the vector before `size()` is
read and silently turn the request into a zero-byte no-op.

## Payload readback evidence

The focused carry test preloads source 256, so its page ID is 1 rather than an
ambiguous all-zero page. Before execution, it reads HBM metadata back and
verifies L0 count 1 and first page ID 1. After carrying into L1, it verifies:

- L0 count is 0;
- L1 count is 1 in the high 32-bit lane of the shared word;
- L1 first packed page ID is 1;
- old and new edge payloads both retain source 256;
- page-list payload and count writes are present in the byte ledger.

## SST-HBM evidence

| Scenario | Cycles | Backend requests | Page-ID bytes | Count bytes | Result |
| --- | ---: | ---: | ---: | ---: | --- |
| Amazon L0 | 7,187 | 1,399 | 8 | 128 | exact |
| Carry + hot | 8,736 | 1,943 | 16 | 320 | exact |
| Weighted SSSP | 33,866 | 4,196 | 8 | 128 | exact |

All scenarios use the source-shaped 32-channel AXI profile and SST/DRAMSim3
backend and report zero result/frontier mismatches.

Relative to the preceding milestones, Amazon changes from 7,139 cycles and
1,382 requests to 7,187 and 1,399. The extra 17 requests are one page-ID word
and sixteen packed count words. Carry changes from 8,402 cycles and 1,901
requests to 8,736 and 1,943; its two target page-list words and forty count
words are on the serial critical path. These are formerly omitted HBM writes,
not an artificial timing penalty.

## Claim boundary

This is `structural_execution_driven` ABI evidence. It makes the persistent
page-list representation available to later cursor modeling, but the current
carry engine does not yet consume returned page-list, page-epoch, bitmap,
page-base, and row-offset payloads to discover sources. Target graph writes are
also still queued after merge completion. Therefore this closes metadata
correctness and traffic accounting, not full carry timing.

## Reproduction

```bash
cd /home/chuxiao/spine-cycle-sim

cmake --build build/cycle-core -j2
build/cycle-core/cpp/spine_cycle_core_tests spine_carry_hbm_level_payload
ctest --test-dir build/cycle-core --output-on-failure
python3 -m unittest discover -s tests
make -C cpp/sst -j2

python3 scripts/run_sst_spine_vertical.py \
  --scenario amazon_l0 --no-build \
  --out-dir results/sst_spine_page_list_amazon_final_20260724

python3 scripts/run_sst_spine_vertical.py \
  --scenario carry_hot --no-build \
  --out-dir results/sst_spine_page_list_carry_final_20260724

python3 scripts/run_sst_spine_vertical.py \
  --scenario weighted_sssp --no-build \
  --out-dir results/sst_spine_page_list_weighted_20260724
```

Machine-readable evidence is in
`docs/evidence/spine_page_list_metadata_20260724_summary.json`.
