# Spine graph index payload path

> Historical milestone. The page-base and row-offset limitations recorded here
> are closed by `docs/spine_exact_range_task_reader_20260724.md`.

Date: 2026-07-24
Branch: `codex/fine-grained-cycle-sim`
HLS reference: `origin/reduce-levels-for-routing` at `afb8199a2ca8d3fd208b985324bf4d8719e2b839`

## Scope

This milestone moves the fixed-level graph index from zero-filled timing-only
writes to explicit HLS-shaped payloads. It also makes the reader's first index
decision depend on an HBM response:

`maintenance index construction -> graph AXI write -> payload store ->`
`reader graph AXI read -> bitmap decode -> source-row gate`

The maintenance path now encodes:

- four 64-bit source bitmap words per touched 256-vertex page;
- sparse 32-bit page-base entries plus the terminal row count;
- packed 32-bit CSR row offsets;
- packed 16-bit destination-partition masks for each source row;
- the existing 64-bit edge records.

The field meanings and packing follow `spine_partitioned.hpp`. In particular,
the row mask contains destination partition bits; it is not a source ID or a
source offset within the page.

The reader issues bitmap, page-base, row-offset, and mask reads for each active
source/occupied level. It waits for the reads to complete before building tile
work. The bitmap response is decoded and a cleared source bit suppresses the
row even if the logical level container still contains edges.

## Anti-bypass evidence

The C++ test `spine_reader_hbm_graph_payload` verifies both payload layout and
control dependence:

1. Build a two-row level containing `src=0, dst=1` and `src=256, dst=2`.
2. Inspect HBM and require both page bitmap bits, page bases `[0, 1]`, row
   offsets `[0, 1, 2]`, and destination-partition masks `[1, 1]`.
3. Run the reader with only source 0 active and observe its edge.
4. Clear only source 0's HBM bitmap word while leaving the logical level
   unchanged.
5. Reset the reader and require zero emitted edges, one bitmap miss, and zero
   edge-payload reads.

A reader that decides row presence from `SpineL0State` fails step 5.

## Online SST evidence

All scenarios use the shared AXI payload path and the SST
MemHierarchy/DRAMSim3 timing backend. Correctness, the AXI/backend/DRAM request
ledger, and the new index payload ledger must all pass.

| scenario | cycles | DRAM requests | index written | index read | bitmap misses |
| --- | ---: | ---: | ---: | ---: | ---: |
| Amazon L0 exact | 4,608 | 545 | 64 B | 32 B | 0 |
| carry + hot | 4,806 | 598 | 128 B | 64 B | 0 |
| weighted SSSP, 6 rounds | 22,640 | 2,412 | 88 B | `[32, 64, 64, 64, 32, 0]` B | `[0, 0, 0, 0, 0, 0]` |

Frozen summaries:

- `docs/evidence/sst_spine_graph_index_payload_amazon_l0_20260724_summary.json`
- `docs/evidence/sst_spine_graph_index_payload_carry_hot_20260724_summary.json`
- `docs/evidence/sst_spine_graph_index_payload_weighted_sssp_20260724_summary.json`

## Reproduction

```bash
cd /home/chuxiao/spine-cycle-sim

cmake --build build/cycle-core -j2
ctest --test-dir build/cycle-core --output-on-failure
python3 -m unittest tests.test_sst_spine_vertical

make -C cpp/sst -j2
python3 scripts/run_sst_spine_vertical.py \
  --scenario amazon_l0 \
  --out-dir results/sst_spine_graph_index_payload_amazon_l0_20260724 \
  --no-build
python3 scripts/run_sst_spine_vertical.py \
  --scenario carry_hot \
  --out-dir results/sst_spine_graph_index_payload_carry_hot_20260724 \
  --no-build
python3 scripts/run_sst_spine_vertical.py \
  --scenario weighted_sssp \
  --out-dir results/sst_spine_graph_index_payload_weighted_sssp_20260724 \
  --no-build
```

## Claim boundary

This closes the source-bitmap value bypass. It does not make the complete
reader payload-driven:

- page-base, row-offset, and row-mask payloads are HLS-shaped, transported,
  read, and counted, but the reader does not yet decode them to recover the
  row number, edge range, or destination-family eligibility;
- level occupancy, slice/page epochs, page lists, and source enumeration still
  depend partly on logical state or timing-only metadata;
- tile grouping still traverses the logical level directory before each edge
  value is fetched from HBM;
- maintenance and reader issue one component memory task at a time instead of
  reproducing all pipelined/outstanding HLS loops;
- the current reader assumes the fixed default Spine layout rather than a
  fully propagated configurable architecture profile.

The accepted evidence tier remains `structural_execution_driven`, not full
HLS-cycle equivalence or hardware calibration.
