# Candidate10 Publication Real-Data Coverage

## Current answer

The committed evidence is now a broad and correctness-gated compact-slice
evaluation, but it is not a full-dataset evaluation. It contains 102 unique
Spine versus GraSU+ReGraph pairs and 234 system rows. Every performance row
passes the architecture-precision oracle, an independent mathematical oracle,
the final graph-state check, and the paired cross-system state check.

The five GraSU temporal datasets are represented by deterministic 8192-edge
file-order compact slices. All three required algorithms, weighted SSSP, Full
PageRank, and thresholded residual PageRank, cover insertion batches 1, 8, and
64. Full PageRank additionally covers insert, delete, mixed, and weight-change
updates. AU, WK, and BC cover dense batches 64, 512, and 4096, with the largest
batch equal to 50% of the base graph. A separate 50K-edge Amazon Full PageRank
case demonstrates correctness and host completion at a larger scale.

The physical-memory matrix covers all three algorithms, five datasets, and both
architectures at insertion batch 8. Accepted requests equal DRAM commands;
request bytes, 64-byte burst amplification, row hits, activates/precharges,
read latency, and finite AXIS/AXI/HBM backpressure counters are present. Full
and residual PageRank use direct controller windows. Weighted SSSP uses an
exact, independently rerun cold-prefix subtraction at a quiescent boundary.
All three algorithm windows are aligned and the frozen compact-slice coverage
contract passes.

The paper-facing TeX entry point is
`docs/paper/candidate10_evaluation_figures.tex`. It contains correctness, E2E,
algorithm ranking, update throughput, small-batch scaling, logical locality,
physical HBM behavior, dense-batch crossover, HBM energy, and routed PPA/timing
figures. Missing evidence always renders as an explicit gate placeholder.

## Claim boundary

These inputs preserve real topology and temporal file order, but compact-ID
extraction changes partition occupancy and graph scale. The current evidence
supports architectural behavior and compact-workload comparisons. It does not
support an unsliced full-dataset, multi-partition scalability, total-chip
energy, or iso-functional PPA claim.

The remaining mandatory work beyond the compact-slice contract is:

1. run unsliced or explicitly scaled multi-partition real datasets;
2. add matched on-chip power/activity evidence to the existing HBM-only energy;
3. close or clearly report the remaining routed timing misses;
4. add optional scalability and ablation sweeps after the mandatory matrix.

## Reproduce the audit

```bash
cd /home/chuxiao/spine-cycle-sim-publication
python3 scripts/audit_candidate10_publication_coverage.py \
  --out-dir docs/evidence/candidate10_publication_coverage_20260727
```

The expected compact-slice status is `PASS`. Full-dataset and total-energy
claims remain separately gated by the claim boundary above.
