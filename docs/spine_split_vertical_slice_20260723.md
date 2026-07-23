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

## Claims boundary

Implemented mechanisms:

- source-value request/response dependency;
- fixed-channel graph, active-bin, metadata, vertex-state, active-output,
  bitmap, and result AXI traffic;
- payload release only after HBM response;
- finite forward and reverse AXIS queues;
- tile grouping, bounded tiny-edge buffering, scattered gather/store;
- one weighted SSSP fanout pass with exact payload correctness.

Not yet implemented:

- the complete count/generation/diagnostic stream protocol;
- full-tile load/replay/store after the 4,096-edge threshold;
- repeated frontier iterations to convergence;
- hot families and carry levels in the reader;
- overlap/prefetch matching HLS scheduling;
- running this architecture component on the SST-HBM backend;
- Full PageRank and thresholded residual PageRank in timed compute.

Accordingly, this slice is functional and structural evidence. It is not yet a
headline latency, algorithm-complete, or Spine-versus-GraSU comparison result.
