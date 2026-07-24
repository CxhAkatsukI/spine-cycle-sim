# Spine exact range-task reader

Date: 2026-07-24
Branch: `codex/fine-grained-cycle-sim`
HLS reference: `origin/reduce-levels-for-routing` at
`afb8199a2ca8d3fd208b985324bf4d8719e2b839`

## Why this milestone was required

The previous simulator reader used the HBM bitmap only as a presence gate, then
walked `SpineL0State` to group logical edges by tile and fetched every emitted
edge once. The latest HLS reader does materially more work:

1. load the 32-family by 11-level metadata cache;
2. use bitmap rank, page base, and row offsets to recover an exact source row;
3. read every edge in that row once to validate it and split it into contiguous
   64K-vertex tile ranges;
4. create 128-bit range descriptors;
5. clear, prefix, scatter, and verify 256 tile bins;
6. replay the descriptors and read every edge a second time before sending it
   through the PartConv AXIS stream.

The old path therefore undercounted edge payload traffic by 2x and omitted the
descriptor construction/binning control work.

![Exact range-task reader](figures/spine_exact_range_task_reader.svg)

## Implemented behavior

`SpineSplitReader` now follows the exact-path control structure from
`spine_partitioned.hpp`:

- one selected bitmap-word read; a missing bit stops the lookup immediately;
- all 11 level-cache entries are checked for every active source/family,
  including empty levels (176 checks per source without hot families);
- only a present source triggers preceding bitmap-word reads for rank;
- packed page-base and row-offset payloads determine `[start, end)`;
- construction reads decode actual HBM edge payloads and reject an out-of-range,
  wrong-partition, or decreasing destination;
- contiguous same-tile edges become range descriptors with the HLS field limits;
- active gate (16,384), descriptor capacity (65,536), construction budget
  (1,048,576 payloads), start width (26 bits), and length width (24 bits) are
  enforced;
- tile state uses 256 clear cycles, 256 prefix cycles, one scatter cycle per
  descriptor, and 256 cursor-verification cycles;
- replay reads the HBM edge payloads again and validates that each destination
  belongs to the descriptor tile before emitting it.

The reader exports separate index, construction, replay, task, binning, path,
fallback, and error counters. The PartConv AXIS/compute interface is unchanged.

## Anti-bypass tests

`spine_reader_hbm_graph_payload` executes six reader rounds while leaving the
logical level container unchanged:

1. overwrite the first edge payload and require the changed edge/proposal;
2. clear the source bitmap and require no page-base, row, construction, replay,
   or output work;
3. change page base from row 0 to row 1 and require the second HBM edge;
4. restore page base but set row 0 to `[0, 0)` and require no edge.
5. activate source 130 and require the earlier bitmap words to give rank 1;
6. clear source 0's earlier bitmap bit, keep source 130's selected bit set, and
   require rank 0 to redirect the same active source to row 0.

This test fails if edge values, source presence, row number, or edge range are
recovered from the Python/C++ logical graph instead of HBM payloads.

## SST-DRAMSim3 evidence

All request counts below close exactly against completed DRAM reads+writes, and
all graph/frontier correctness mismatches are zero.

The frozen architecture profile still identifies the available
hardware-validated `9c08763148644df262c0d374e782bc834f4c0f4f` build. The
reader behavior in this milestone is mapped to the newer `afb8199...` HLS
source. Therefore these runs validate the new structure on the shared memory
profile; they are not a hardware calibration of the new HLS revision.

| scenario | cycles | requests | index reads | construction | replay | tasks |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| Amazon L0 exact | 5,698 | 554 | 24 B | 80 B | 80 B | 5 |
| carry + hot | 6,142 | 599 | 48 B | 24 B | 24 B | 2 |
| weighted SSSP, 6 rounds | 30,725 | 2,425 | `[24,64,64,56,32,8]` B | `[24,24,16,16,8,0]` B | same | `[1,2,2,2,1,0]` |

The weighted run now reports bitmap misses `[0,1,0,0,1,1]`. Those misses are
expected: the device-dirty path probes every active source against every cold
family, and some active sources have no row in an occupied level. The old
logical-state traversal skipped those probes and incorrectly reported no miss.

Frozen summaries:

- `docs/evidence/sst_spine_exact_range_amazon_l0_20260724_summary.json`
- `docs/evidence/sst_spine_exact_range_carry_hot_20260724_summary.json`
- `docs/evidence/sst_spine_exact_range_weighted_sssp_20260724_summary.json`

## Reproduction

```bash
cd /home/chuxiao/spine-cycle-sim

cmake --build build/cycle-core -j2
ctest --test-dir build/cycle-core --output-on-failure
python3 -m unittest discover -s tests

make -C cpp/sst -j2
python3 scripts/run_sst_spine_vertical.py \
  --scenario amazon_l0 \
  --out-dir results/sst_spine_exact_range_amazon_l0_20260724 \
  --no-build
python3 scripts/run_sst_spine_vertical.py \
  --scenario carry_hot \
  --out-dir results/sst_spine_exact_range_carry_hot_20260724 \
  --no-build
python3 scripts/run_sst_spine_vertical.py \
  --scenario weighted_sssp \
  --out-dir results/sst_spine_exact_range_weighted_sssp_20260724 \
  --no-build
```

## Remaining fidelity gaps

This is `structural_execution_driven` evidence, not HLS-cycle equivalence.

1. **Metadata payload authority.** Level occupancy, edge count, offsets, and
   slice epoch are still selected from `SpineL0State`/the configured layout.
   Metadata and page-epoch reads are timed, but their returned payloads are not
   decoded and compared. Maintenance metadata writes are still partly
   timing-only.
2. **Active-record payload authority.** The 256-bit HLS active record contains
   source, source value, 11 level masks, and a hot-shard mask. The simulator
   reads 32 B per record, but source enumeration and values still come from the
   source-value protocol/logical frontier.
3. **Fallback execution and diagnostics.** Active-gate, descriptor-capacity,
   payload-budget, metadata, destination, prefix, and descriptor failures are
   detected and classified. The old host touched-tile fallback and the HLS
   diagnostic/dirty acknowledgement stream are not executed end to end.
4. **Pipelined memory issue.** Reader and maintenance component tasks are issued
   serially. The shared AXI/HBM backend supports beats, bursts, outstanding
   requests, finite response queues, and contention, but this reader does not
   yet reproduce the HLS loop-level request windows and overlap.
5. **On-chip implementation timing.** Clear/prefix/scatter/verify have explicit
   cycle work, but the descriptor/active/level URAMs and tile BRAM arrays are
   not yet connected to bank/port conflict models.
6. **Clock and host protocol closure.** Kernel clock/CDC/controller and measured
   host-round launch/transfer windows remain configurable approximations rather
   than calibrated protocol traces.

The next fidelity milestone should close items 1 and 2 before optimizing AXI
overlap: payload-authoritative metadata and active records are correctness
dependencies, while outstanding issue primarily changes timing.
