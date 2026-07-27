# Candidate10 Publication Coverage Audit

This fail-closed audit combines the committed compact real-data pilot with the
five-dataset GraSU temporal Full PageRank matrix. It does not infer Cartesian
coverage from independent sets of datasets, algorithms, batches, or scenarios.

The current status is `INCOMPLETE`: 77 unique paired runs are correct, all five
GraSU reference datasets have batch-1/8/64 Full PageRank results, and all five
have insert-batch-8 results for each of the three required algorithms.
Controller-level row-hit and latency evidence is present for the Full PageRank
subset, and three real topologies have Full PageRank batch-64/512/4096 dense
sweeps. Weight changes, the complete three-algorithm batch cross-product, and
the full queue/backpressure metric set remain open.

Reproduce with:

```bash
python3 scripts/audit_candidate10_publication_coverage.py \
  --out-dir docs/evidence/candidate10_publication_coverage_20260727
```
