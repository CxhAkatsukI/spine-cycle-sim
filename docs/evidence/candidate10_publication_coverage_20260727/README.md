# Candidate10 Publication Coverage Audit

This fail-closed audit combines the committed compact real-data matrices. It
does not infer Cartesian coverage from independent sets of datasets,
algorithms, batches, or scenarios.

The current status is `INCOMPLETE`: 102 unique paired runs are correct. All five
GraSU reference datasets have batch-1/8/64 insertion results for each of the
three required algorithms; the Full PageRank update matrix covers insert,
delete, mixed, and weight-change scenarios; and three real topologies have Full
PageRank batch-64/512/4096 dense sweeps. Controller-level request, byte,
row-hit, latency, burst-amplification, and finite AXIS/AXI/HBM backpressure
metrics are complete for all three algorithms. The only failed formal gate is
three-algorithm physical-window alignment: Spine weighted SSSP includes cold
initialization in its controller window, so that algorithm is diagnostic only
and is excluded from the phase-aligned physical comparison plot.

The inputs remain compact real-topology slices, so closing these gates does not
by itself establish a full-dataset or multi-partition scalability claim.

Reproduce with:

```bash
python3 scripts/audit_candidate10_publication_coverage.py \
  --out-dir docs/evidence/candidate10_publication_coverage_20260727
```
