# Candidate10 GraSU Temporal Full PageRank, Batch 8

## Scope

This bundle contains the first paper-referenced real-topology comparison for
the frozen Candidate10 normalized Spine and conversion-free GraSU+ReGraph
profiles. It covers compact file-order slices from all five GraSU temporal
datasets (AU, SU, WK, SO, and BC), with insert, delete, and mixed batches of
eight user mutations. Full PageRank runs for three fixed iterations.

There are 15 architecture pairs and 30 system runs. Every row passes the
architecture-precision oracle, independent float64 oracle, cross-system final
rank check, dynamic graph state check, and memory request conservation check.

## Results

`Spine speedup` is GraSU+ReGraph time divided by Spine time; values below one
favor GraSU+ReGraph.

| Scope | Pairs | Spine wins | Spine E2E speedup | Spine update speedup | Spine compute speedup |
|---|---:|---:|---:|---:|---:|
| All | 15 | 0 | 0.337x | 0.000696x | 0.426x |

GraSU+ReGraph is therefore about 2.97x faster end to end on geometric average.
The gap is not exclusively a structure-update effect: its update path is about
1436x faster for this tiny batch, while its Full PageRank compute window is
about 2.35x faster.

GraSU+ReGraph issues 0.531x as many backend requests but requests 3.27x as many
logical bytes. Controller evidence resolves the apparent tension: its mean
DRAM row-hit rate is 94.6%, versus 84.4% for Spine, and its mean read latency is
25.5 versus 31.9 DRAM cycles. Logical address adjacency and physical row-hit
rate remain separate metrics in the evidence.

Insert, delete, and mixed groups have nearly identical E2E time. At this graph
and batch size, three full PageRank iterations plus Spine's fixed maintenance
scans dominate the eight mutation-specific operations.

## Boundaries

These are 8192-edge compact slices, not full GraSU datasets. Compact IDs alter
the original partition occupancy, and every input remains within one normalized
destination partition. Edges preserve source-file order; global timestamp order
is not reconstructed. This bundle supports a topology-breadth pilot for batch-8
Full PageRank, not full-dataset, multi-partition, dense-batch, SSSP, or residual
PageRank claims.

DRAM counters cover active channels only. The energy values exclude idle HBM
channels and on-chip logic, so no cross-system total-energy claim is made here.

## Reproduction

```bash
cd /home/chuxiao/spine-cycle-sim

python3 scripts/run_hls_pagerank_real_comparison.py \
  --input-manifest configs/experiments/candidate10_grasu_temporal_compact_batches_v1_20260727.json \
  --profile-set candidate10_hls_v3 \
  --run-id grasu_au_insert_u8 --run-id grasu_au_delete_u8 --run-id grasu_au_mixed_u8 \
  --run-id grasu_su_insert_u8 --run-id grasu_su_delete_u8 --run-id grasu_su_mixed_u8 \
  --run-id grasu_wk_insert_u8 --run-id grasu_wk_delete_u8 --run-id grasu_wk_mixed_u8 \
  --run-id grasu_so_insert_u8 --run-id grasu_so_delete_u8 --run-id grasu_so_mixed_u8 \
  --run-id grasu_bc_insert_u8 --run-id grasu_bc_delete_u8 --run-id grasu_bc_mixed_u8 \
  --out-dir /data/tmp/chuxiao/candidate10_grasu_temporal_full_pr_batch8_20260727 \
  --lib-dir build/sst --jobs 4 --timeout-seconds 1800 \
  --max-cycles 100000000 --no-build --resume

python3 scripts/analyze_candidate10_temporal_real_pagerank.py \
  --matrix-dir /data/tmp/chuxiao/candidate10_grasu_temporal_full_pr_batch8_20260727 \
  --out-dir docs/evidence/candidate10_grasu_temporal_full_pr_batch8_20260727 \
  --paper-data-dir docs/paper/data

cd docs/paper
latexmk -pdf -interaction=nonstopmode -halt-on-error \
  candidate10_evaluation_figures.tex
```

`raw_results.tar.gz` contains both parent tables, each system's raw result, and
all per-channel final DRAMSim3 JSON files used by the analysis.
