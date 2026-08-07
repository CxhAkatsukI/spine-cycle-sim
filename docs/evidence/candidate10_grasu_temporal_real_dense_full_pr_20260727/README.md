# Candidate10 GraSU Temporal Real-Dense Full PageRank

## Scope

This bundle sweeps insertion batches 64, 512, and 4096 on AU, WK, and BC
compact real-topology slices. Every base graph has 8192 edges, so the update
ratios are 0.78125%, 6.25%, and 50%. Full PageRank runs for three iterations.

The matrix contains nine architecture pairs and 18 system runs. Every row
passes both PageRank oracles, the cross-system rank check, graph-state check,
and DRAM request conservation check.

## Results

`Spine speedup` is GraSU+ReGraph E2E time divided by Spine E2E time. Values
below one favor GraSU+ReGraph. Values are geometric means across AU, WK, and BC.

| Batch | Update/base | Spine E2E ms | GraSU+ReGraph E2E ms | Spine speedup |
|---:|---:|---:|---:|---:|
| 64 | 0.78% | 12.678 | 4.697 | 0.371x |
| 512 | 6.25% | 13.403 | 4.791 | 0.357x |
| 4096 | 50% | 16.982 | 5.433 | 0.320x |

GraSU+ReGraph's E2E advantage grows from about 2.70x to 3.13x. From batch 64
to 4096, Spine E2E rises about 34%, versus about 16% for GraSU+ReGraph. No
capacity failure occurs at batch 4096 on these slices.

## Boundaries

These are compact slices, not complete source datasets, and every input fits
one normalized destination partition. The sweep covers insertion and Full
PageRank only. It establishes a real-topology dense trend within that scope,
not a full-dataset or multi-partition capacity claim.

## Reproduction

```bash
cd /home/chuxiao/spine-cycle-sim
python3 scripts/analyze_candidate10_temporal_dense_pagerank.py \
  --matrix-dir /data/tmp/chuxiao/candidate10_grasu_temporal_full_pr_batch8_20260727 \
  --out-dir docs/evidence/candidate10_grasu_temporal_real_dense_full_pr_20260727 \
  --paper-data-dir docs/paper/data
```

`raw_results.tar.gz` contains the parent matrix, each selected raw system
result, and all active-channel DRAMSim3 statistics.
