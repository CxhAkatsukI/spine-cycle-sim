# Candidate10 v3 Dense Full PageRank

## Claim boundary

This experiment compares the frozen 150 MHz Candidate10 normalized profiles:

- `spine_candidate10_normalized_v1`
- `grasu_regraph_candidate10_normalized_hls_pagerank_v3`

The comparison is conversion-free, execution-driven, and uses the same finite
FIFO, AXI, arbitration, and DRAMSim3-backed HBM machinery. It is a normalized
structural simulator result. It is not native FPGA timing, cycle-for-cycle
hardware calibration, or an iso-resource claim. Matching whole-system Full
PageRank HLS evidence is reported separately.

## Workload

Every run starts from an 8,192-vertex directed ring with 8,192 edges and then
inserts 8, 64, 512, or 4,096 edges. Updates are either concentrated on a few
sources or scattered across the source range. Both architectures execute three
Full PageRank iterations at damping 0.85 over identical hash-pinned graph and
update files.

Each timing pair must pass the float32 architecture oracle, independent float64
mathematical oracle, and cross-system rank-vector comparison. All 16 system
runs and all eight pairs passed. Every cross-system maximum absolute rank
difference is zero.

## Timing result

`GraSU speedup` below is `Spine E2E / GraSU E2E`; values above one favor
GraSU+ReGraph.

| Shape | Batch | Spine E2E (ms) | GraSU E2E (ms) | GraSU speedup | Spine update (ms) | GraSU update (ms) |
|---|---:|---:|---:|---:|---:|---:|
| concentrated | 8 | 34.976 | 7.488 | 4.67x | 2.850 | 0.001 |
| concentrated | 64 | 34.990 | 7.497 | 4.67x | 2.861 | 0.008 |
| concentrated | 512 | 35.166 | 7.578 | 4.64x | 2.949 | 0.078 |
| concentrated | 4,096 | 36.161 | 8.344 | 4.33x | 3.657 | 0.836 |
| scattered | 8 | 34.972 | 7.488 | 4.67x | 2.853 | 0.001 |
| scattered | 64 | 35.053 | 7.495 | 4.68x | 2.920 | 0.009 |
| scattered | 512 | 35.679 | 7.555 | 4.72x | 3.440 | 0.069 |
| scattered | 4,096 | 40.247 | 8.037 | 5.01x | 7.617 | 0.551 |

The eight-pair GraSU E2E speedup geometric mean is 4.67x. The compute portion
is nearly fixed across this sweep: Spine takes 32.119--32.630 ms and
GraSU+ReGraph takes 7.486--7.509 ms. The current structural advantage therefore
does not come only from update handling; the normalized GraSU/ReGraph
gather/apply path is also substantially shorter for this dense Full PageRank
workload.

At batch 4,096 the update shape separates the two systems. Scattered sources
raise Spine update time from 3.657 to 7.617 ms, while they reduce GraSU update
time from 0.836 to 0.551 ms. This is a specific optimization lead for Spine's
source-distributed maintenance work, not evidence that every scattered graph
behaves identically.

## Memory result

Across the eight pairs, GraSU/ReGraph issues 0.359--0.460x as many backend
requests as Spine, but requests 1.552--1.729x as many payload bytes. The two
architectures use different access widths and burst shapes, so request count
and requested-byte count lead to opposite rankings here. Neither metric may be
used as a proxy for DRAM traffic or energy without the corresponding byte and
DRAMSim3 evidence.

The committed pair table labels DRAM energy ratios invalid because it covers
only active HBM channels and excludes on-chip and idle-channel energy.

## Capacity boundary

The four capacity endpoints reproduced the frozen profile contract:

| Batch | Final edges | Spine | GraSU+ReGraph | Timing ratio |
|---:|---:|---|---|---|
| 8,192 | 16,384 | PASS at L1 boundary | profile capacity reject | undefined |
| 16,384 | 24,576 | expected L1 family overflow | profile capacity reject | undefined |

The GraSU rejection is the pinned 4,096-entry PageRank degree-reorder limit,
not a measured xclbin failure. The Spine overflow is the current single-family
L1 target capacity. No performance ratio is reported where either system
cannot enter the common timing window.

## Runtime

With four concurrent jobs, the eight-pair timing matrix completed in 193.75
host seconds. The four serial capacity endpoints completed in 223.66 seconds.
These are simulator-throughput measurements, not accelerator latency.

## Reproduction

```bash
cd /home/chuxiao/spine-cycle-sim
python3 scripts/prepare_hls_full_pagerank_dense_batches.py --verify-only
python3 scripts/run_hls_pagerank_real_comparison.py \
  --profile-set candidate10_hls_v3 \
  --input-manifest configs/experiments/hls_full_pagerank_dense_batch_sweep_20260726.json \
  --out-dir /data/tmp/chuxiao/candidate10_hls_v3_dense_full_20260727 \
  --jobs 4 --timeout-seconds 900 --max-cycles 200000000 --no-build
python3 scripts/run_spine_dense_capacity_cliff.py \
  --profile-set candidate10_hls_v3 \
  --input-manifest configs/experiments/hls_full_pagerank_dense_batch_sweep_20260726.json \
  --out-dir /data/tmp/chuxiao/candidate10_hls_v3_dense_capacity_20260727 \
  --timeout-seconds 900 --max-cycles 200000000 --no-build
```

Compact evidence is frozen under
`docs/evidence/candidate10_hls_v3_dense_full_pagerank_20260727/`. The raw child
directories remain under `/data/tmp/chuxiao/` and are intentionally not
committed.
