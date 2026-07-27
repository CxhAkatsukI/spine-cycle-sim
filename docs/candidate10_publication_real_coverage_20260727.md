# Candidate10 Publication Real-Data Coverage

## Current answer

The committed real-data evidence is a correct pilot, but it is not yet broad
enough for the final claims requested by the senior student.

Current coverage is three compact real-edge slices (Amazon-2008, Web-Google,
and soc-Flickr-und), three algorithms, three update scenarios, and one batch
size of eight user mutations. This produces 27 complete architecture pairs and
54 system runs, all of which pass the correctness gates. One additional
Amazon-2008 50K-edge Full PageRank case checks host runtime and a synthetic
dense sweep checks the batch-size mechanism.

The original pilot alone misses important dimensions: none of its three compact
inputs is one of GraSU's five temporal datasets, it has no small-batch size
sweep or mixed-update row, its dense tests use a synthetic ring, and its memory
report classifies logical address adjacency rather than controller behavior.

The first follow-up matrix now covers all five GraSU datasets for Full PageRank
at batches 1, 8, and 64. It contains 40 pairs and 80 system runs: insert/delete
at every batch, plus mixed updates at batches 8 and 64. Every row is correct and
includes controller row-hit and read-latency evidence. The broader publication
gate remains incomplete because SSSP and residual PageRank have not yet been
run on those five inputs, weight changes remain pending, and dense real-topology
tests remain pending. Explicit AXI-issue and HBM queue/backpressure stall
counters are also still absent.

A second follow-up matrix covers weighted SSSP, Full PageRank, and thresholded
residual PageRank on all five reference slices for insert batches of eight. Its
15 pairs and 30 system runs all pass their independent mathematical oracle and
cross-system final-state check. This closes the five-dataset, three-algorithm
correctness breadth gate, but not the full three-algorithm batch-size cross
product.

The audit combines the old and new evidence only as input rows. Every formal
gate checks the required cross-product, so three algorithms on old datasets
plus one algorithm on five reference datasets cannot accidentally pass the
five-dataset, three-algorithm requirement.

## Publication gate

`configs/experiments/candidate10_publication_real_coverage_v1.json` freezes the
minimum evidence required before a final plot can be called complete. It uses
the five GraSU temporal datasets as the primary dynamic-graph corpus and a
representative subset of Dynamic-ACTS real datasets for topology and scale.

Every performance row must satisfy all three correctness checks:

1. architecture-precision oracle;
2. independent mathematical oracle;
3. cross-system final state.

The small-batch matrix uses batches 1, 8, and 64. Dense behavior uses batches
64, 512, and 4096 and reports both the absolute batch and the ratio of updated
edges to base edges. Update throughput is successful user mutations per second;
internal delete-plus-insert amplification is reported separately.

## Reproduce the current audit

```bash
cd /home/chuxiao/spine-cycle-sim
python3 scripts/audit_candidate10_publication_coverage.py \
  --out-dir /data/tmp/chuxiao/candidate10_publication_coverage_20260727
```

The expected current status is `INCOMPLETE`. This is a deliberate fail-closed
result, not a test failure.

The paper-figure entry point is
`docs/paper/candidate10_evaluation_figures.tex`. It compiles now with explicit
missing-evidence placeholders; final CSVs will replace the placeholders as the
real matrices close.
