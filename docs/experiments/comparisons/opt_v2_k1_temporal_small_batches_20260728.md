# Optimized Spine versus K=1 GraSU+ReGraph: temporal small batches

## Scope

This evidence compares `spine_candidate10_opt_v2_reader_working_set` against
the frozen, resource-normalized K=1 GraSU+ReGraph profiles. It covers all three
required algorithms on five real temporal topologies, with insertion batches
of 1, 8, and 64 mutations:

- Weighted SSSP;
- Full PageRank;
- thresholded Residual PageRank.

The matrix contains 45 architecture pairs and 90 simulator executions. Every
execution passed its architecture-precision oracle, independent mathematical
oracle, request ledger, and cross-system final-state check.

## Results

At batch 8, geometric-mean Spine speedup over GraSU+ReGraph is:

| Algorithm | Spine (ms) | GraSU+ReGraph (ms) | Spine speedup |
|---|---:|---:|---:|
| Weighted SSSP | 2.362 | 4.144 | 1.754x |
| Full PageRank | 8.646 | 4.466 | 0.517x |
| Residual PageRank | 178.073 | 131.609 | 0.739x |

Changing the batch from 1 to 64 does not reverse any algorithm-level result.
Weighted SSSP speedup decreases from 1.803x to 1.595x, Full PageRank remains
near 0.51x, and Residual PageRank remains near 0.74x.

The main limitation is structural: all five 8192-edge compact slices fit in
one destination partition in both systems. These results support the
small-batch, real-topology claim, but not a multi-partition or full-graph
claim. The follow-up matrix uses a 540000-edge AskUbuntu graph with 157107
vertices, which activates three ReGraph destination partitions.

## Reproduction

Build or verify the tracked temporal corpus, run the three real-comparison
runners with the optimized Spine and frozen K=1 profiles, then analyze them:

```bash
cd /home/chuxiao/spine-cycle-sim-publication
python3 scripts/prepare_candidate10_grasu_temporal_workloads.py --verify-only

python3 scripts/analyze_candidate10_opt_v2_k1_temporal_small_batches.py \
  --weighted-dir /data/tmp/chuxiao/opt_v2_k1_temporal_weighted_small_batches_20260728 \
  --full-pagerank-dir /data/tmp/chuxiao/opt_v2_k1_temporal_fullpr_small_batches_20260728 \
  --residual-dir /data/tmp/chuxiao/opt_v2_k1_temporal_residual_small_batches_20260728 \
  --out-dir /data/tmp/chuxiao/opt_v2_k1_temporal_small_batches_analysis_20260728
```

The committed evidence bundle is
`docs/evidence/candidate10_opt_v2_k1_temporal_small_batches_20260728`. It
contains the analysis manifest, pair/system rows, grouped tables, correctness
coverage, and a compressed archive of all raw simulator results.

