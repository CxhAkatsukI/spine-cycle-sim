# Candidate10 Three-Algorithm Small-Batch Matrix

## Scope

This evidence expands the frozen Candidate10 normalized comparison across:

- weighted SSSP, three-iteration Full PageRank, and thresholded residual
  PageRank;
- insertion batches of 1, 8, and 64 user mutations; and
- compact file-order slices from all five GraSU temporal datasets.

The complete matrix contains 45 architecture pairs and 90 system runs. Every
pair passes the architecture-precision oracle, independent mathematical
oracle, cross-system final-state check, updated graph-state check, and DRAM
request conservation check.

## Results

`Spine speedup` is GraSU+ReGraph E2E time divided by Spine E2E time. Values
above one favor Spine. Each value is the geometric mean of five datasets.

| Algorithm | Batch | Spine E2E ms | GraSU+ReGraph E2E ms | Spine speedup |
|---|---:|---:|---:|---:|
| Weighted SSSP | 1 | 2.297 | 4.142 | 1.803x |
| Weighted SSSP | 8 | 2.364 | 4.144 | 1.753x |
| Weighted SSSP | 64 | 2.632 | 4.162 | 1.581x |
| Full PageRank | 1 | 11.037 | 3.725 | 0.337x |
| Full PageRank | 8 | 11.070 | 3.727 | 0.337x |
| Full PageRank | 64 | 11.220 | 3.739 | 0.333x |
| Residual PageRank | 1 | 236.410 | 107.597 | 0.455x |
| Residual PageRank | 8 | 237.152 | 108.375 | 0.457x |
| Residual PageRank | 64 | 239.301 | 109.440 | 0.457x |

Spine wins the aggregate weighted-SSSP comparison, while GraSU+ReGraph wins
both PageRank variants. The ranking remains stable from batch 1 through 64, so
algorithm dataflow dominates the small update-size effect in this matrix.

## Boundaries

Each graph is an 8192-edge compact real-topology slice, not a complete source
dataset, and fits one normalized destination partition. This evidence supports
three-algorithm small-batch ranking and trend claims. It does not support a
full-dataset, multi-partition, dense-update, physical backpressure, or complete
energy claim.

The simulator uses source vertex zero for weighted SSSP, three fixed iterations
for Full PageRank, and damping 0.85, epsilon `1e-6`, and at most 256 iterations
for residual PageRank.

## Reproduction

The batch-8 rows come from the previously frozen three-algorithm evidence and
the Full PageRank batch sweep. The following two runners generate the missing
batch-1 and batch-64 rows; select the ten insertion run IDs from the input
manifest (`grasu_{au,su,wk,so,bc}_insert_{u1,u64}`).

```bash
cd /home/chuxiao/spine-cycle-sim

python3 scripts/run_hls_weighted_real_comparison.py \
  --input-manifest configs/experiments/candidate10_grasu_temporal_compact_batches_v1_20260727.json \
  --profile-set candidate10_hls_v3 \
  --run-id grasu_au_insert_u1 --run-id grasu_au_insert_u64 \
  --run-id grasu_su_insert_u1 --run-id grasu_su_insert_u64 \
  --run-id grasu_wk_insert_u1 --run-id grasu_wk_insert_u64 \
  --run-id grasu_so_insert_u1 --run-id grasu_so_insert_u64 \
  --run-id grasu_bc_insert_u1 --run-id grasu_bc_insert_u64 \
  --out-dir /data/tmp/chuxiao/candidate10_grasu_temporal_weighted_sssp_small_batches_20260727 \
  --lib-dir build/sst --jobs 4 --timeout-seconds 1200 \
  --max-cycles 100000000 --no-build

python3 scripts/run_hls_residual_pagerank_real_comparison.py \
  --input-manifest configs/experiments/candidate10_grasu_temporal_compact_batches_v1_20260727.json \
  --profile-set candidate10_hls_v3 \
  --run-id grasu_au_insert_u1 --run-id grasu_au_insert_u64 \
  --run-id grasu_su_insert_u1 --run-id grasu_su_insert_u64 \
  --run-id grasu_wk_insert_u1 --run-id grasu_wk_insert_u64 \
  --run-id grasu_so_insert_u1 --run-id grasu_so_insert_u64 \
  --run-id grasu_bc_insert_u1 --run-id grasu_bc_insert_u64 \
  --out-dir /data/tmp/chuxiao/candidate10_grasu_temporal_residual_small_batches_20260727 \
  --lib-dir build/sst --jobs 4 --timeout-seconds 1200 \
  --max-cycles 100000000 --no-build

python3 scripts/analyze_candidate10_temporal_three_algorithm_small_batches.py \
  --weighted-gap-dir /data/tmp/chuxiao/candidate10_grasu_temporal_weighted_sssp_small_batches_20260727 \
  --residual-gap-dir /data/tmp/chuxiao/candidate10_grasu_temporal_residual_small_batches_20260727 \
  --out-dir docs/evidence/candidate10_grasu_temporal_three_algorithm_small_batches_20260727 \
  --paper-data-dir docs/paper/data
```

`gap_raw_results.tar.gz` preserves the newly generated raw system results. The
analysis manifest hashes every derived table and the archive.
