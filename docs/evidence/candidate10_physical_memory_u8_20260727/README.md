# Candidate10 physical-memory and backpressure evidence

This bundle records 15 correctness-gated architecture pairs: weighted SSSP,
Full PageRank, and thresholded residual PageRank on batch-8 insertion over
compact 8192-edge slices from the five GraSU temporal datasets. It contains 30
system rows and the archived child results and per-channel DRAMSim3 statistics.

## Validated contract

- Every architecture and independent mathematical oracle passes, and paired
  Spine/GraSU+ReGraph final states match.
- Accepted backend requests equal DRAM reads plus writes on every row.
- Requested bytes, nominal 64-byte transfers, and read/write ledgers close.
- Every row exports finite AXIS, AXI request-FIFO, HBM request-queue, and HBM
  response-queue stall counters.
- All 30 measured child runs and five cold-prefix runs loaded the same SST
  plugin, SHA-256
  `9094f527995f9ea0a10d686ee7f90236400eca0619b634f039e98061bac328b8`,
  through an exact `--lib-path` with the requested build directory first.

## Phase-aligned result

| Algorithm | System | DRAM requests | Row-hit rate | 64B/requested-byte amplification | Mean read latency (cycles) | HBM queue stalls/request | AXIS stalls/request |
| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: |
| SSSP | Spine | 105,419 | 0.889 | 8.023x | 29.02 | 1.820 | 0.000 |
| SSSP | GraSU+ReGraph | 799,703 | 0.957 | 1.174x | 26.28 | 1.063 | 0.200 |
| Full PR | Spine | 824,128 | 0.849 | 8.781x | 31.63 | 3.014 | 0.000 |
| Full PR | GraSU+ReGraph | 433,914 | 0.946 | 1.454x | 25.20 | 1.048 | 0.368 |
| Residual PR | Spine | 23,945,305 | 0.866 | 10.076x | 33.04 | 2.782 | 0.000 |
| Residual PR | GraSU+ReGraph | 21,237,248 | 0.957 | 1.235x | 27.30 | 1.231 | 0.007 |

Under these compact, single-partition workloads, Spine generates substantially
more physical 64-byte transfer amplification and HBM admission pressure. In
SSSP it nevertheless issues 7.59x fewer DRAM requests than GraSU+ReGraph,
showing that request volume and request efficiency are distinct bottlenecks.
This supports a memory-path diagnosis for these cases; it is not yet a
full-dataset or multi-partition conclusion.

Weighted SSSP is phase-aligned by subtracting an independently rerun cold-only
prefix from each cumulative per-channel DRAM result. Every baseline exactly
matches the dynamic run's frozen cold cycles, requests, rounds, per-round
cycles, maintenance cycles, final distance vector, architecture profile, and
plugin identity. The phase boundary is quiescent: Spine is idle and backend
outstanding requests are zero. DRAM command counts, latency histograms, and
energy are subtracted per channel; AXIS/AXI counters are already update-scoped,
while cumulative HBM request/response stalls are cold-subtracted.

Stalls are rejected port/request attempts, not unique stalled cycles. Multiple
ports can contribute events in one simulated cycle. Only active HBM channels
are instantiated in these runs, so the energy field is not total-board energy.

## Reproduction

```bash
cd /home/chuxiao/spine-cycle-sim-publication
make -C cpp/sst BUILD_DIR=../../build/sst-stalls -j4

RUNS=(grasu_au_insert_u8 grasu_su_insert_u8 grasu_wk_insert_u8 \
      grasu_so_insert_u8 grasu_bc_insert_u8)
RUN_ARGS=()
for run in "${RUNS[@]}"; do RUN_ARGS+=(--run-id "$run"); done

python3 scripts/run_hls_weighted_real_comparison.py \
  --input-manifest configs/experiments/candidate10_grasu_temporal_compact_batches_v1_20260727.json \
  --profile-set candidate10_hls_v3 "${RUN_ARGS[@]}" \
  --out-dir /data/tmp/chuxiao/repro_physical_weighted \
  --lib-dir build/sst-stalls --jobs 4 --timeout-seconds 1200 \
  --max-cycles 100000000 --no-build

python3 scripts/run_hls_pagerank_real_comparison.py \
  --input-manifest configs/experiments/candidate10_grasu_temporal_compact_batches_v1_20260727.json \
  --profile-set candidate10_hls_v3 "${RUN_ARGS[@]}" \
  --out-dir /data/tmp/chuxiao/repro_physical_full_pr \
  --lib-dir build/sst-stalls --jobs 4 --timeout-seconds 1200 \
  --max-cycles 100000000 --no-build

python3 scripts/run_hls_residual_pagerank_real_comparison.py \
  --input-manifest configs/experiments/candidate10_grasu_temporal_compact_batches_v1_20260727.json \
  --profile-set candidate10_hls_v3 "${RUN_ARGS[@]}" \
  --out-dir /data/tmp/chuxiao/repro_physical_residual_pr \
  --lib-dir build/sst-stalls --jobs 4 --timeout-seconds 1200 \
  --max-cycles 100000000 --no-build

python3 scripts/run_candidate10_spine_weighted_cold_baselines.py \
  --dynamic-dir /data/tmp/chuxiao/repro_physical_weighted \
  --out-dir /data/tmp/chuxiao/repro_physical_weighted_cold \
  --lib-dir build/sst-stalls --jobs 5 --timeout-seconds 1200 \
  --max-cycles 100000000 --no-build

python3 scripts/analyze_candidate10_physical_memory.py \
  --weighted-dir /data/tmp/chuxiao/repro_physical_weighted \
  --weighted-cold-dir /data/tmp/chuxiao/repro_physical_weighted_cold \
  --full-pagerank-dir /data/tmp/chuxiao/repro_physical_full_pr \
  --residual-pagerank-dir /data/tmp/chuxiao/repro_physical_residual_pr \
  --out-dir /data/tmp/chuxiao/repro_physical_analysis
```

Verify the committed bundle with `sha256sum -c SHA256SUMS` from this directory.
