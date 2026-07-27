# Candidate10 GraSU Temporal Three-Algorithm Matrix

## Scope

This bundle compares weighted SSSP, three-iteration Full PageRank, and
thresholded residual PageRank on compact file-order slices from all five GraSU
temporal datasets. Every run uses an insertion batch of eight user mutations.

The matrix contains 15 architecture pairs and 30 system runs. Every row passes
the architecture-precision oracle, independent mathematical oracle,
cross-system final-state check, graph-state check, and DRAM request ledger.

## Results

`Spine speedup` is GraSU+ReGraph E2E time divided by Spine E2E time. Values
above one favor Spine.

| Algorithm | Pairs | Spine E2E ms | GraSU+ReGraph E2E ms | Spine speedup |
|---|---:|---:|---:|---:|
| Weighted SSSP | 5 | 2.364 | 4.144 | 1.753x |
| Full PageRank | 5 | 11.070 | 3.727 | 0.337x |
| Residual PageRank | 5 | 237.152 | 108.375 | 0.457x |

Spine wins weighted SSSP on four of five datasets, but loses on WK (0.497x).
GraSU+ReGraph wins every Full and residual PageRank case. The ranking therefore
depends on both algorithm and topology; a single algorithm cannot establish a
general architecture ordering.

Weighted SSSP uses source vertex zero and the independent Dijkstra oracle's
minimum synchronous superstep count for each updated graph. Full PageRank uses
three iterations. Residual PageRank uses damping 0.85, epsilon `1e-6`, and
converges in 78 to 105 iterations on these slices.

## Boundaries

Each input is an 8192-edge compact slice, not a complete source dataset, and
fits one normalized destination partition. The formal cross-algorithm matrix
covers insert batch 8 only. Broader Full PageRank update and batch behavior is
reported separately.

The SSSP E2E window is aligned, but Spine's raw controller counters still
include cold initialization. Therefore `phase_aligned_physical_memory_complete`
is false and this bundle does not populate the cross-algorithm physical-memory
figure. Active-channel DRAM energy also excludes on-chip and idle-channel
energy.

## Reproduction

```bash
cd /home/chuxiao/spine-cycle-sim
python3 scripts/analyze_candidate10_temporal_three_algorithms.py \
  --weighted-dir /data/tmp/chuxiao/candidate10_grasu_temporal_weighted_sssp_smoke_20260727 \
  --full-pagerank-dir /data/tmp/chuxiao/candidate10_grasu_temporal_full_pr_batch8_20260727 \
  --residual-dir /data/tmp/chuxiao/candidate10_grasu_temporal_residual_smoke_20260727 \
  --out-dir docs/evidence/candidate10_grasu_temporal_three_algorithms_insert_u8_20260727 \
  --paper-data-dir docs/paper/data
```

`raw_results.tar.gz` contains the three parent matrices, each selected raw
system result, and all active-channel DRAMSim3 statistics.
