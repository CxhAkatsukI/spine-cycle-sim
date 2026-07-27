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

The first follow-up matrix now covers all five GraSU datasets for batch-8 Full
PageRank insert/delete/mixed updates. Its 15 pairs and 30 system runs are all
correct and include controller row-hit and read-latency evidence. The broader
publication gate remains incomplete because SSSP and residual PageRank have not
yet been run on those five inputs, batch 1/64 sweeps remain pending, and dense
real-topology tests remain pending. Controller row-hit and latency counters are
now available for this Full PageRank subset, but explicit AXI-issue and HBM
queue/backpressure stall counters are still absent.

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
