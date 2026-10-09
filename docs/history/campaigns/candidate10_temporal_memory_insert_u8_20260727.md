# Candidate10 temporal memory traffic evidence

## Scope

This evidence compares phase-aligned accepted backend requests for Spine and the
conversion-free normalized GraSU+ReGraph system. It covers weighted SSSP, Full
PageRank, and thresholded residual PageRank on five compact real-topology slices
with insert batches of eight.

Every selected run must pass its architecture-precision oracle, independent
mathematical oracle, cross-system final-state check, CSV hash check, and exact
two-system coverage check before it enters an aggregate or plot.

## Reproduce

The committed three-algorithm archive contains the exact source CSVs used here.

```bash
cd /home/chuxiao/spine-cycle-sim-publication
rm -rf /tmp/candidate10-memory-raw
mkdir -p /tmp/candidate10-memory-raw
tar -xzf \
  docs/evidence/candidate10_grasu_temporal_three_algorithms_insert_u8_20260727/raw_results.tar.gz \
  -C /tmp/candidate10-memory-raw

python3 scripts/analyze_real_memory_traffic.py \
  --weighted-dir /tmp/candidate10-memory-raw/raw/weighted_sssp \
  --full-pagerank-dir /tmp/candidate10-memory-raw/raw/full_pagerank \
  --residual-pagerank-dir /tmp/candidate10-memory-raw/raw/thresholded_residual_pagerank \
  --input-manifest configs/experiments/candidate10_grasu_temporal_compact_batches_v1_20260727.json \
  --source-archive docs/evidence/candidate10_grasu_temporal_three_algorithms_insert_u8_20260727/raw_results.tar.gz \
  --paper-data-dir docs/paper/data \
  --out-dir docs/evidence/candidate10_grasu_temporal_memory_insert_u8_20260727

mkdir -p /tmp/candidate10-paper
cd docs/paper
latexmk -pdf -interaction=nonstopmode -halt-on-error \
  -outdir=/tmp/candidate10-paper candidate10_evaluation_figures.tex
```

## Results

Across the five correct pairs per algorithm, the geometric-mean
GraSU+ReGraph-to-Spine requested-byte ratios are:

| Algorithm | Byte ratio |
|---|---:|
| Weighted SSSP | 39.61x |
| Full PageRank | 3.27x |
| Thresholded residual PageRank | 7.42x |

The traffic-volume advantage does not imply a locality advantage. After
excluding the first request in each initiator/operation stream, Spine's
discontinuous-byte fractions are 22.8%, 76.7%, and 87.6%; GraSU+ReGraph's are
5.8%, 5.6%, and 13.5%, respectively. The architectures therefore trade fewer
requested bytes against different logical address-stream locality.

## Claim boundary

`contiguous`, `repeated`, and `discontinuous` classify accepted logical requests
per initiator and operation. They are not DRAM row hits. Requested bytes also
exclude AXI/HBM burst amplification and controller-internal transfer granularity.
The inputs are 8192-edge compact file-order slices, not full datasets. These
results support a request-volume and logical-locality comparison; a physical HBM
traffic or row-buffer-locality claim still requires aligned controller counters.
