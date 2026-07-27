# Candidate10 Publication Coverage Audit

This fail-closed audit combines the committed compact real-data pilot with the
five-dataset GraSU temporal Full PageRank matrix. It does not infer Cartesian
coverage from independent sets of datasets, algorithms, batches, or scenarios.

The current status is `INCOMPLETE`: 67 paired runs are correct, all five GraSU
reference datasets have batch-1/8/64 Full PageRank results, and controller-level
row-hit and latency evidence is present for that subset. Three-algorithm
coverage on those datasets, weight changes, real-topology dense batches, and
the complete queue/backpressure metric set remain open.

Reproduce with:

```bash
python3 scripts/audit_candidate10_publication_coverage.py \
  --out-dir docs/evidence/candidate10_publication_coverage_20260727
```
