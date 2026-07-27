# Candidate10 Publication Coverage Audit

This fail-closed audit combines the committed compact real-data matrices. It
does not infer Cartesian coverage from independent sets of datasets,
algorithms, batches, or scenarios.

The current status is `INCOMPLETE`: 102 unique paired runs are correct. All five
GraSU reference datasets have batch-1/8/64 insertion results for each of the
three required algorithms; the Full PageRank update matrix covers insert,
delete, mixed, and weight-change scenarios; and three real topologies have Full
PageRank batch-64/512/4096 dense sweeps. Controller-level traffic, row-hit, and
latency evidence is present. The only failed formal gate is the complete
physical-memory metric set, which still requires explicit AXI request-FIFO and
HBM queue/backpressure counters on the committed matrix.

The inputs remain compact real-topology slices, so closing these gates does not
by itself establish a full-dataset or multi-partition scalability claim.

Reproduce with:

```bash
python3 scripts/audit_candidate10_publication_coverage.py \
  --out-dir docs/evidence/candidate10_publication_coverage_20260727
```
