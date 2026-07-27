# Candidate10 Matched Weighted-SSSP HBM Energy

## Scope

This evidence compares Candidate10-v3 weighted SSSP on the same three compact
holdout slices used by the publication PageRank energy matrix. Both systems
instantiate all 32 DRAMSim3 HBM controllers.

Spine's dynamic result is cumulative: cold graph construction followed by the
eight-edge insertion and SSSP execution. The committed cold matrix independently
reproduces that prefix and requires an exact match in cycles, backend requests,
final values, rounds, round cycles, maintenance cycles, architecture profile,
and SST plugin identity at a quiescent boundary. The analyzer subtracts every
DRAM command and energy component per controller before forming a ratio.

| Dataset | Total HBM G+R / Spine | Command dynamic | Background + refresh |
|---|---:|---:|---:|
| Amazon 2008 | 1.055x | 3.821x | 1.042x |
| Web Google | 0.581x | 1.899x | 0.575x |
| Soc Flickr | 1.660x | 7.434x | 1.635x |
| Geometric mean | 1.006x | 3.779x | 0.993x |

The total HBM energy is effectively tied in geometric mean on these three
slices. GraSU+ReGraph issues substantially more command-dynamic DRAM work, while
runtime-dependent background and refresh energy determines the total on each
individual slice.

## Reproduction

```bash
cd /home/chuxiao/spine-cycle-sim-publication

python3 scripts/run_hls_weighted_real_comparison.py \
  --input-manifest configs/experiments/hls_weighted_real_small_batches_20260726.json \
  --profile-set candidate10_hls_v3 \
  --run-id real_amazon_2008_insert_u8 \
  --run-id real_web_google_insert_u8 \
  --run-id real_soc_flickr_und_insert_u8 \
  --out-dir /data/tmp/chuxiao/repro_weighted_energy_dynamic \
  --lib-dir build/sst-stalls --jobs 4 --timeout-seconds 1200 \
  --max-cycles 100000000 --instantiate-all-hbm-channels --no-build

python3 scripts/run_candidate10_spine_weighted_cold_baselines.py \
  --input-manifest configs/experiments/hls_weighted_real_small_batches_20260726.json \
  --dynamic-dir /data/tmp/chuxiao/repro_weighted_energy_dynamic \
  --out-dir /data/tmp/chuxiao/repro_weighted_energy_cold \
  --run-id real_amazon_2008_insert_u8 \
  --run-id real_web_google_insert_u8 \
  --run-id real_soc_flickr_und_insert_u8 \
  --lib-dir build/sst-stalls --jobs 3 --timeout-seconds 1200 \
  --max-cycles 100000000 --instantiate-all-hbm-channels --no-build

python3 scripts/analyze_matched_weighted_sssp_energy.py \
  --dynamic-dir /data/tmp/chuxiao/repro_weighted_energy_dynamic \
  --cold-dir /data/tmp/chuxiao/repro_weighted_energy_cold \
  --out-dir /data/tmp/chuxiao/repro_weighted_energy_analysis
```

## Claim Boundary

This is simulated HBM energy, not total accelerator or board energy. On-chip
logic, memory, FIFO, interconnect, and clock energy are intentionally excluded.
