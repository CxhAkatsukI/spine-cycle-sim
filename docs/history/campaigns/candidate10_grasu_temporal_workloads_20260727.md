# Candidate10 GraSU Temporal Workloads

## Purpose

This corpus adds the five timestamped real graphs used by GraSU: AU, SU, WK,
SO, and BC. It is the paper-referenced topology-breadth tier of the Candidate10
evaluation; it does not replace the later full-dataset scale tier.

Each initial graph contains 8192 unique, non-self edges selected in source-file
order. The next 4096 unique edges form the real insertion candidate pool.
Observed vertex IDs are compacted deterministically. The committed manifest
records source archive hashes, selected timestamp bounds, mapping hashes,
graph/update hashes, and the exact extraction policy.

For each dataset the corpus contains batch sizes 1, 8, 64, 512, and 4096 and
four update scenarios:

- `insert`: later source-file edges;
- `delete`: deterministic spread over live real edges;
- `mixed`: equal-size delete and insert subsets;
- `weight_change`: explicit delete-old then insert-new records.

The batch-one mixed case is omitted because one mutation cannot contain both an
insert and a delete. There are 95 run inputs in total. Update streams are sorted
by `(src,dst)` with delete-before-insert ordering for the same edge, matching the
Spine maintenance input contract.

## Scope boundary

The source files carry timestamps, but this extraction does not globally sort
the complete archive by timestamp. It preserves source-file order and states so
in the manifest. Delete, mixed, and weight-change batches are derived from the
real topology; only insertion candidates are later events from the source file.

Compact IDs materially change original partition occupancy. Results from this
corpus may support topology-breadth and update-pattern claims, but not complete
dataset, multi-partition, or scalability claims.

## Reproduction

```bash
cd /home/chuxiao/spine-cycle-sim

python3 scripts/prepare_candidate10_grasu_temporal_workloads.py
python3 scripts/prepare_candidate10_grasu_temporal_workloads.py --verify-only
```

The input manifest is
`configs/experiments/candidate10_grasu_temporal_compact_batches_v1_20260727.json`.

The first PageRank smoke is reproducible with:

```bash
python3 scripts/run_hls_pagerank_real_comparison.py \
  --input-manifest configs/experiments/candidate10_grasu_temporal_compact_batches_v1_20260727.json \
  --profile-set candidate10_hls_v3 \
  --run-id grasu_au_insert_u8 \
  --out-dir /data/tmp/chuxiao/candidate10_grasu_temporal_full_pr_batch8_20260727 \
  --lib-dir build/sst --jobs 2 --timeout-seconds 1800 \
  --max-cycles 100000000 --no-build --resume
```
