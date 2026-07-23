# Spine split reader/compute vertical slice

Date: 2026-07-23  
Branch: `codex/fine-grained-cycle-sim`

## Scope

This extends the stable-profile L0 maintenance slice through the split
convergence topology used by the accepted xclbin:

`L0 state -> fused reader -> edge AXIS(32) -> tiny SSSP compute`

A reverse `value AXIS(32)` carries source values from compute to reader. Both
streams are finite registered FIFOs with no same-cycle fall-through.

The committed acceptance test reads `amazon_top1_exact.slice`, runs L0
maintenance, requests source vertex 2 through the stream protocol, reads the
persisted edge payloads through graph HBM ports, and relaxes them in compute.
The reader cannot emit an edge before its graph AXI response. Compute cannot
relax a destination before its vertex-state AXI response.

## Structural result

The ten destination IDs occupy five 65,536-vertex tiles. All five select the
tiny path because each contains at most four edges, below the 4,096-edge
threshold.

| component counter | expected |
| --- | ---: |
| source requests / responses | 1 / 1 |
| reader tiles / edges | 5 / 10 |
| reader active-bin / metadata / graph bytes | 32 / 64 / 224 |
| compute fast / full tiles | 5 / 0 |
| processed edges | 10 |
| gathered / scattered vertex words | 10 / 10 |
| vertex-state read / write bytes | 44 / 40 |
| active-output write bytes | 80 |
| active-bitmap bytes | 16 |
| compute-result write bytes | 384 |
| forward AXIS transfers | 22 |
| reverse AXIS transfers | 1 |

The 22 forward words are one source request, five tile-begin markers, ten edge
payloads, five tile-end markers, and one done marker. The next frontier has ten
vertices, and every destination distance is exactly one. This agrees with the
weighted SSSP functional oracle for the same file-backed graph.

The 224 graph bytes comprise four 16-byte CSR index-word reads (bitmap,
page-base, row-offset, and row-mask) plus ten 16-byte edge payload reads.

## Reproduction

```bash
cd /home/chuxiao/spine-cycle-sim
cmake --build build/cycle-core
build/cycle-core/cpp/spine_cycle_core_tests
ctest --test-dir build/cycle-core --output-on-failure
python3 -m unittest tests.test_algorithms -v
git diff --check
```

The C++ suite prints an `EVIDENCE spine_vertical_slice ...` line containing
the deterministic MockMemory cycle spans and maximum edge-stream occupancy.
Those cycle spans are regression evidence only; they are not hardware
calibration because MockMemory is not the formal memory backend.

Run the same component on the formal SST-HBM backend with:

```bash
python3 scripts/run_sst_spine_vertical.py \
  --scenario amazon_l0 \
  --out-dir results/sst_spine_vertical_levels_20260723
```

The first accepted run produced:

| SST/DRAMSim3 evidence | value |
| --- | ---: |
| data cycles | 4,622 |
| backend requests | 551 |
| DRAM completed reads / writes | 489 / 62 |
| DRAM ACT / PRE | 47 / 39 |
| read + write row hits | 470 |
| backend max outstanding | 4 |
| backend/response-queue stalls | 0 / 0 |
| memory-only DRAMSim3 energy | 67,128,624 pJ |

All 32 configured pseudo-channels emitted statistics. The backend request count
exactly equals completed DRAM reads plus writes, and all architecture counters
remain identical to the MockMemory structural run. Both the expected distance
values and the exact next-frontier vertex set match the one-step oracle. The
committed aggregate is
`docs/evidence/sst_spine_levels_20260723_summary.json`; per-channel raw JSON
is reproduced by the command above.

The increase from the earlier 157-request slice is a fidelity correction: the
reader now fetches the occupied word for all 32 x 11 level-cache entries and
the remaining metadata for occupied levels. The carry/hot acceptance scenario
is documented in `spine_carry_hot_vertical_slice_20260723.md`.

## Claims boundary

Implemented mechanisms:

- source-value request/response dependency;
- fixed-channel graph, active-bin, metadata, vertex-state, active-output,
  bitmap, and result AXI traffic;
- payload release only after HBM response;
- finite forward and reverse AXIS queues;
- tile grouping, bounded tiny-edge buffering, scattered gather/store;
- independent cold/hot target levels and all-level reader traversal;
- one weighted SSSP fanout pass with exact payload correctness.

Not yet implemented:

- the complete count/generation/diagnostic stream protocol;
- full-tile load/replay/store after the 4,096-edge threshold;
- repeated frontier iterations to convergence;
- overlap/prefetch matching HLS scheduling;
- Full PageRank and thresholded residual PageRank in timed compute.

Accordingly, this slice is functional and structural evidence. It is not yet a
headline latency, algorithm-complete, or Spine-versus-GraSU comparison result.
