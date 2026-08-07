# Candidate10 GraSU Temporal Full PageRank Small Batches

## Scope

This bundle expands the frozen Candidate10 normalized comparison to batches 1,
8, and 64 on compact file-order slices from all five GraSU temporal datasets.
It includes insert and delete at every batch size and mixed updates at batches 8
and 64. A one-mutation batch cannot contain both an insertion and a deletion.

The matrix contains 40 architecture pairs and 80 system runs. Every row passes
the architecture-precision oracle, independent float64 oracle, cross-system
rank check, updated graph-state check, and memory request conservation check.

## Results

The table reports geometric means. Throughput is successful user mutations per
second, expressed in millions; it does not count internal physical records.

| Batch | Pairs | Spine update M/s | GraSU+ReGraph update M/s | Spine E2E ms | GraSU+ReGraph E2E ms |
|---:|---:|---:|---:|---:|---:|
| 1 | 10 | 0.000448 | 1.746 | 11.038 | 3.725 |
| 8 | 15 | 0.003571 | 5.130 | 11.055 | 3.726 |
| 64 | 15 | 0.027785 | 7.079 | 11.153 | 3.735 |

The Full PageRank E2E ratio is almost flat: GraSU+ReGraph is about 2.96x to
2.99x faster. Three full iterations dominate these small updates. Update-only
throughput rises with batch size because fixed setup and Spine maintenance scan
costs are amortized, but the E2E window barely moves.

## Boundaries

Each base graph is an 8192-edge compact slice, not a full source dataset. The
compact ID mapping changes original partition occupancy, and every graph fits
one normalized destination partition. This bundle supports a Full PageRank
small-batch trend claim, not SSSP, residual PageRank, full-dataset, dense-batch,
or multi-partition claims.

DRAM energy covers active channels only and excludes on-chip and idle-channel
energy. Controller row-hit and latency metrics are included, but explicit AXI
issue and HBM queue/backpressure stall counters remain outside this evidence.

## Reproduction

```bash
cd /home/chuxiao/spine-cycle-sim

mapfile -t run_ids < <(jq -r \
  '.runs[] | select((.batch_size == 1 or .batch_size == 8 or .batch_size == 64) and (.scenario == "insert" or .scenario == "delete" or .scenario == "mixed")) | .run_id' \
  configs/experiments/candidate10_grasu_temporal_compact_batches_v1_20260727.json)
args=()
for run_id in "${run_ids[@]}"; do args+=(--run-id "$run_id"); done

python3 scripts/run_hls_pagerank_real_comparison.py \
  --input-manifest configs/experiments/candidate10_grasu_temporal_compact_batches_v1_20260727.json \
  --profile-set candidate10_hls_v3 "${args[@]}" \
  --out-dir /data/tmp/chuxiao/candidate10_grasu_temporal_full_pr_batch8_20260727 \
  --lib-dir build/sst --jobs 4 --timeout-seconds 1800 \
  --max-cycles 100000000 --no-build --resume

python3 scripts/analyze_candidate10_temporal_small_batches.py \
  --matrix-dir /data/tmp/chuxiao/candidate10_grasu_temporal_full_pr_batch8_20260727 \
  --out-dir docs/evidence/candidate10_grasu_temporal_full_pr_small_batches_20260727 \
  --paper-data-dir docs/paper/data
```

`raw_results.tar.gz` contains the parent tables, every system result, and each
active channel's final DRAMSim3 statistics used by the analysis.
