# Candidate10 Full PageRank differential scenarios

## Scope

This evidence combines the previously correctness-gated batch-8 Full PageRank
baseline for insert, delete, and mixed updates with five new weight-change
pairs. It covers five compact real-topology GraSU temporal slices, four update
scenarios, 20 architecture pairs, and 40 system rows.

Each pair passes the float32 architecture oracle, independent float64 oracle,
cross-system final-rank comparison, graph-state check, and DRAM request ledger.
The analyzer also checks the update semantics directly:

| Scenario | User mutations | Physical records | Final edge delta |
|---|---:|---:|---:|
| Insert | 8 | 8 | +8 |
| Delete | 8 | 8 | -8 |
| Mixed | 8 | 8 | 0 |
| Weight change | 8 | 16 | 0 |

## Result

The geometric-mean E2E ratio is nearly invariant across update type: Spine
takes 2.96x to 2.97x the GraSU+ReGraph time. Full PageRank's three iterations
and Spine's fixed maintenance work dominate these eight-mutation batches.

GraSU+ReGraph update throughput is 4.97 to 5.28 million user mutations/s for
insert, delete, and mixed, then drops to 3.25 million for weight change because
each semantic change lowers to delete-old plus insert-new. Spine remains near
0.00357 million user mutations/s in all four cases because fixed maintenance
scans dominate mutation-specific work at this scale.

## Reproduce

```bash
cd /home/chuxiao/spine-cycle-sim-publication
python3 scripts/analyze_candidate10_temporal_differential_pagerank.py \
  --baseline-evidence-dir docs/evidence/candidate10_grasu_temporal_full_pr_batch8_20260727 \
  --weight-change-matrix-dir /data/tmp/chuxiao/candidate10_grasu_temporal_full_pr_weight_change_u8_20260727 \
  --input-manifest configs/experiments/candidate10_grasu_temporal_compact_batches_v1_20260727.json \
  --out-dir docs/evidence/candidate10_grasu_temporal_full_pr_differential_u8_20260727 \
  --paper-data-dir docs/paper/data

python3 scripts/audit_candidate10_publication_coverage.py \
  --out-dir docs/evidence/candidate10_publication_coverage_20260727

cd docs/paper
latexmk -pdf -interaction=nonstopmode -halt-on-error \
  -outdir=/tmp/candidate10-paper candidate10_evaluation_figures.tex
```

`weight_change_raw_results.tar.gz` contains the exact parent matrix tables, raw
system results, and active-channel DRAMSim3 counters for the five new pairs.
The other 15 pairs are referenced through the committed baseline evidence and
its SHA-256 hashes rather than duplicated.

## Boundaries

These inputs are 8192-edge compact file-order slices, not full datasets. Every
input remains within one normalized destination partition. Delete, mixed, and
weight-change batches are derived from real topology. Update throughput counts
successful semantic mutations, not lowered physical records.
