# Normalized shared comparison analysis

## Purpose and claim boundary

`scripts/analyze_shared_comparison_matrix.py` is the fail-closed analysis layer
for the normalized, conversion-free Spine versus GraSU/PMA-native ReGraph
matrix. It does not run either simulator. It accepts evidence only after the
parent matrix reports `PASS`, `complete_matrix: true`, no failure, two system
rows for every hash-pinned workload, and one pair for every run ID.

All timing ratios are labeled **normalized structural execution-driven**. They
are not native HLS cycle measurements or hardware-calibrated absolute latency.
The analyzer does not include a GraSU-to-ReGraph conversion stage because the
normalized architecture intentionally removes that stage.

## Independent evidence gates

The analyzer reloads each child result and every instantiated channel's raw
`dramsim3.json`. It rejects the matrix if:

- source manifest content no longer matches the hash recorded by the parent;
- row or pair counts do not cover the source manifest exactly;
- a run ID/system identity is duplicated or missing;
- architecture, mathematical, or combined mismatch count is nonzero;
- raw DRAM reads plus writes differ from the backend request ledger;
- raw DRAM channel count differs from the sparse binding manifest;
- a recomputed pair speedup differs from `pairs.csv`.

This layer therefore checks raw evidence rather than trusting a precomputed
headline table.

## Outputs

The output directory contains:

| File | Contents |
|---|---|
| `system_details.csv` | cycles, maintenance/PMA-update split, backend traffic, row-hit rate, latency, stalls, and sparse DRAM energy for every system row |
| `pair_details.csv` | pairwise cycle speedup, request ratio, row-hit rates, and sparse DRAM energy ratio |
| `group_summary.csv` | overall and per-algorithm/dataset-kind/role geometric mean, median, range, and win counts |
| `bottleneck_summary.csv` | count of structure/update-dominant, balanced, and compute-dominant rows per system |
| `analysis_manifest.json` | input hashes, implementation fingerprints, output hashes, claim labels, and embedded summaries |

The phase classifier calls a row structure/update-dominant at 55% or more,
compute-dominant at 45% or less, and balanced in between. For Spine the first
phase is maintenance; for GraSU/ReGraph it is PMA update. This is a coarse E2E
phase split, not a claim that every internal pipeline stall has already been
assigned to a unique root cause.

## Memory and energy interpretation

Row-hit rate is computed from raw DRAMSim3 read/write completions and row-hit
counters. Read latency is request-weighted across channels. DRAMSim3 does not
always emit a per-write latency histogram for every completed write, so write
latency includes an explicit coverage fraction and must not be interpreted
without it.

Sparse runs instantiate only channels reachable by the architecture/workload.
Their `total_energy` includes DRAMSim3 energy for those instantiated channels
over the simulated interval, but excludes idle/background energy of unbound
physical channels. The analyzer therefore labels it
`sparse_active_channel_dramsim3_only`. It does not claim full 32-channel DRAM
energy, total accelerator energy, FPGA board power, or ASIC energy.

## Reproduction

```bash
cd /home/chuxiao/spine-cycle-sim
python3 scripts/prepare_shared_comparison_workloads.py --verify-only
python3 scripts/run_shared_comparison_matrix.py \
  --out-dir results/shared_comparison_sparse_full_20260725 \
  --jobs 4 \
  --timeout-seconds 1800 \
  --resume \
  --no-build
python3 scripts/analyze_shared_comparison_matrix.py \
  --matrix-dir results/shared_comparison_sparse_full_20260725 \
  --out-dir results/shared_comparison_sparse_analysis_20260725
```

No aggregate performance conclusion is valid until the final matrix and
analysis manifests both report `PASS` with 146 system rows and 73 pairs.
