# Candidate10 v3 Real Small-Batch Comparison

## Scope

This experiment compares the frozen Candidate10 normalized Spine and
conversion-free GraSU+ReGraph simulator profiles on compact file-backed slices
of Amazon-2008, Web-Google, and soc-Flickr-und. Each dataset is exercised with
eight-edge insert, delete, and weight-change batches under all three required
algorithms:

- weighted SSSP;
- Full PageRank with three fixed iterations;
- thresholded residual PageRank with a `1e-6` convergence threshold.

There are 27 paired cases and 54 system runs. Both architectures use 150 MHz
profiles and the common execution-driven finite-FIFO, AXI, pseudo-channel
arbitration, and DRAMSim3 HBM substrate. These are normalized simulator cycles,
not native FPGA measurements or cycle-for-cycle calibration against an xclbin.

## Correctness

All 54 runs and all 27 pairs pass. Each result is checked against the
architecture-precision oracle and an independent mathematical oracle; the
final Spine and GraSU+ReGraph states are then compared across systems. A failed
correctness row is rejected by the analyzer and cannot enter a performance
aggregate.

## Results

`Spine speedup` is `GraSU+ReGraph time / Spine time`; values above one favor
Spine.

| Group | Pairs | Spine E2E wins | E2E speedup geo. mean | Update speedup geo. mean | Compute speedup geo. mean | GraSU/Spine requests |
|---|---:|---:|---:|---:|---:|---:|
| All | 27 | 5 | 0.726x | 0.00198x | 1.246x | 1.511x |
| Weighted SSSP | 9 | 2 | 0.619x | 0.00149x | 2.258x | 1.151x |
| Full PageRank | 9 | 0 | 0.714x | 0.00228x | 0.978x | 1.314x |
| Residual PageRank | 9 | 3 | 0.866x | 0.00228x | 0.877x | 2.281x |
| Amazon-2008 | 9 | 4 | 0.893x | 0.00407x | 1.376x | 2.642x |
| Web-Google | 9 | 0 | 0.578x | 0.00137x | 1.050x | 0.944x |
| soc-Flickr-und | 9 | 1 | 0.743x | 0.00138x | 1.340x | 1.382x |

GraSU+ReGraph is about `1 / 0.726 = 1.38x` faster end to end on geometric
average and wins 22 of 27 cases. This is not because it always computes faster:
Spine's compute-only window is 1.246x faster overall and 2.258x faster for
weighted SSSP. The ranking is reversed by structure maintenance. Across these
eight-user-mutation batches, GraSU+ReGraph's pure update window is about
`1 / 0.001978 = 505x` faster on geometric average.

The mechanism-level conclusion is therefore specific: Candidate10 Spine's
repeated family/partition/level scan is the dominant small-batch E2E weakness,
while its weighted frontier computation is already competitive. A maintenance
optimization can materially change E2E ranking; reducing backend request count
alone is not sufficient, because GraSU+ReGraph issues 1.51x as many requests on
average yet still finishes sooner.

## Timing Windows

The E2E number contains the timed structure update followed by the timed graph
computation. Graph preload/build is outside both systems' measured window.
`Update` is Spine maintenance versus GraSU PMA plus degree update. `Compute` is
the remainder of E2E after subtracting that update window. It is a diagnostic
decomposition, not a claim that update and compute overlap.

The throughput result is deliberately reported per eight input mutations. The
physical PMA record count remains in the evidence for write-amplification
analysis. No-update setup cycles are never converted into fictitious update
throughput.

## Reproduction

```bash
cd /home/chuxiao/spine-cycle-sim

python3 scripts/run_hls_weighted_real_comparison.py \
  --profile-set candidate10_hls_v3 \
  --out-dir /data/tmp/chuxiao/candidate10_hls_v3_real_small_weighted_20260727 \
  --lib-dir build/sst --jobs 2 --timeout-seconds 1800 \
  --max-cycles 100000000 --no-build

python3 scripts/run_hls_pagerank_real_comparison.py \
  --profile-set candidate10_hls_v3 \
  --out-dir /data/tmp/chuxiao/candidate10_hls_v3_real_small_full_pagerank_20260727 \
  --lib-dir build/sst --jobs 2 --timeout-seconds 1800 \
  --max-cycles 100000000 --no-build

python3 scripts/run_hls_residual_pagerank_real_comparison.py \
  --profile-set candidate10_hls_v3 \
  --out-dir /data/tmp/chuxiao/candidate10_hls_v3_real_small_residual_pagerank_20260727 \
  --lib-dir build/sst --jobs 2 --timeout-seconds 1800 \
  --max-cycles 100000000 --no-build

python3 scripts/analyze_candidate10_real_small_batches.py \
  --weighted-dir /data/tmp/chuxiao/candidate10_hls_v3_real_small_weighted_20260727 \
  --full-pagerank-dir /data/tmp/chuxiao/candidate10_hls_v3_real_small_full_pagerank_20260727 \
  --residual-pagerank-dir /data/tmp/chuxiao/candidate10_hls_v3_real_small_residual_pagerank_20260727 \
  --out-dir /data/tmp/chuxiao/candidate10_hls_v3_real_small_analysis_20260727
```

The self-contained compact evidence bundle is
`docs/evidence/candidate10_hls_v3_real_small_batches_20260727/`. It includes
each source matrix manifest and CSV, the combined analysis, and a verified
`SHA256SUMS` file.

## Claim Boundary

- The inputs use real graph files and real topology, but they are compact
  slices rather than complete datasets.
- The result supports small-batch bottleneck and architecture comparisons; it
  does not establish full-dataset throughput or scaling.
- Backend request adjacency classes are not DRAM row-hit classifications.
- Requested bytes exclude controller burst amplification.
- Total energy and iso-resource claims require the separate matched HBM,
  on-chip activity, synthesis resource, and routed timing evidence.
- Exact GraSU+ReGraph HLS feasibility evidence is separate and does not tune
  these frozen simulator results after the fact.
