# HLS-profile Residual PageRank Real-Compact Comparison

## Contract

This matrix runs thresholded signed-residual PageRank after the same nine
real-compact dynamic batches used for weighted SSSP and Full PageRank. Both
systems use damping 0.85, epsilon `1e-6`, activation rule
`abs(residual) > epsilon / vertices`, and a 256-round safety limit.

The timed window excludes initial graph construction and includes differential
structure update, degree-state update where required, and all residual rounds
until the active frontier becomes empty. Every pair must match in external
rank vector, residual vector, per-round frontier-in sizes, and per-round
frontier-out sizes.

## Reproduction

```bash
cd /home/chuxiao/spine-cycle-sim
make -C cpp/sst -j2
python3 scripts/run_hls_residual_pagerank_real_comparison.py \
  --out-dir results/hls_residual_pagerank_memory_locality_final_20260726 \
  --jobs 2 \
  --timeout-seconds 600 \
  --max-cycles 100000000 \
  --no-build
```

The complete matrix took 875.3 seconds with two concurrent workers while the
Full PageRank matrix initially shared the host. The slowest individual
simulated run took 141.9 host seconds. No HBM event,
frontier round, or correctness check was skipped.

## Correctness

All 18 system rows pass architecture and mathematical oracles. All nine pairs
have identical frontier sequences and satisfy the residual bound. Across the
matrix, the maximum external rank difference is `1e-7` and the maximum
residual difference is `1e-14`, both well within the fail-closed `1e-5` state
tolerance. Convergence takes 76 to 100 rounds depending on the final graph.

## Performance

`Spine speedup` is `GraSU time / Spine time`; values above 1 favor Spine.

| Group | Spine E2E speedup | Winner | GraSU / Spine requests |
|---|---:|---|---:|
| All 9 pairs, geometric mean | 0.896 | GraSU by 1.116x | 2.279x |
| Amazon-2008 | 1.239 | Spine by 1.239x | 5.383x |
| web-Google | 0.705 | GraSU by 1.418x | 1.330x |
| soc-Flickr-und | 0.824 | GraSU by 1.214x | 1.653x |

Spine wins all three Amazon cases; GraSU wins all six Web-Google and Flickr
cases. Update type changes the required convergence rounds in a few cases but
does not change the winner within a dataset.

## Architectural interpretation

GraSU/ReGraph residual PageRank still scans and applies over a fixed
65,536-destination partition every round. On the 650-vertex Amazon slice that
creates 5.38x the HBM requests of Spine, allowing Spine's active-source Reader
and smaller state work to win despite its slower 141 MHz clock and expensive
maintenance. At 2.5k to 3k vertices, GraSU's eight-lane pipeline and 200 MHz
clock amortize the fixed sweep enough to win even while issuing more requests.

This is the crossover direction the simulator is meant to expose: reducing
Spine maintenance alone will help small batches, but the Web/Flickr result also
points to Reader/compute throughput as a necessary optimization target.

## Memory locality

Across the nine rows, Spine issues 83,772,800 requested bytes and
GraSU/ReGraph issues 1,757,672,000; the per-pair geometric-mean byte ratio is
23.393x. Of non-first-request bytes, Spine is 55.98% contiguous and 43.21%
discontinuous, while GraSU/ReGraph is 96.99% contiguous and 3.01%
discontinuous. GraSU's PMA sweep is much more sequential but repeatedly moves
the much larger fixed-partition state. These classes describe accepted logical
requests per initiator and operation; they do not claim DRAM row-hit behavior.

## Claim boundary

- The graph slices are real-edge inputs but compact, not full datasets.
- The GraSU/ReGraph residual profile is HLS-equivalent proposed and has no
  compiled PageRank xclbin.
- Timing is execution-driven SST-HBM simulation, not cycle-calibrated hardware
  evidence.
- DRAM energy includes active channels only; on-chip and idle-channel energy
  remain excluded.
- Physical DRAM burst/row locality, arbitrary multi-level checkpoint loading,
  dense batches, and publication-scale runtime remain open gates.
