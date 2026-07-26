# Normalized shared comparison analysis

> This document preserves the earlier v2 matrix. The current HLS-derived v3
> formal result and publication-facing claim boundary are in
> `candidate10_hls_v3_formal_comparison_20260727.md`.

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

## Frozen complete result

The 2026-07-25 run passed all 146 system rows and all 73 pairs with zero
architecture, mathematical, and combined correctness mismatches. No row was
reused from an older simulator fingerprint. Four concurrent jobs completed in
2,219.42 seconds. The slowest child was the intentionally adversarial
gather-bank fan-in residual PageRank case for Spine: 87,217,959 simulated
cycles and 1,202.16 host seconds.

`spine_speedup_over_grasu` is defined as `GraSU/ReGraph cycles / Spine cycles`;
values above one favor Spine.

| Group | Pairs | Spine wins | GraSU/ReGraph wins | Geomean | Median |
|---|---:|---:|---:|---:|---:|
| All | 73 | 48 | 25 | 1.849x | 2.010x |
| Weighted SSSP | 23 | 15 | 8 | 1.956x | 2.793x |
| Dynamic weighted SSSP | 4 | 4 | 0 | 3.081x | 3.134x |
| Full PageRank | 23 | 14 | 9 | 1.650x | 1.064x |
| Thresholded residual PageRank | 23 | 15 | 8 | 1.792x | 1.641x |
| Synthetic | 64 | 43 | 21 | 2.043x | 2.813x |
| Compact real-dataset validation | 9 | 5 | 4 | 0.912x | 1.004x |

The strongest Spine cases are tiny or sparse-frontier graphs where
GraSU/ReGraph still pays its fixed partition gather/apply sweep. The maximum is
7.160x. The strongest GraSU/ReGraph cases are the 4,095--4,097 source-window
graphs: Spine's dirty-source/fallback and level-reader work makes its speedup
fall to 0.357--0.452x. This is a useful optimization direction, not an anomaly
to discard.

The compact real slices prevent a synthetic-only claim: Amazon is close to a
tie for Full PageRank and weighted SSSP and favors Spine for residual PageRank;
Flickr is mixed; Web-Google favors GraSU/ReGraph for all three algorithms.
These slices validate real graph shapes and correctness, but they are too small
to claim full real-dataset performance.

Spine is compute-dominant in 66 of 73 rows, maintenance-dominant in six, and
balanced in one. GraSU/ReGraph is compute-dominant in all 73 rows. This says
most current optimization leverage is in the algorithm/read/gather/apply path,
while the six Spine maintenance-heavy cases remain the right B-stage ablation
targets. It does not replace lower-level stall attribution.

Across the matrix, Spine uses 3.988x fewer backend requests geometrically and
1.401x less active-channel DRAMSim3 energy. Those ratios are not total memory
or accelerator energy. In particular, the compact real-slice active-DRAM
energy ratio is 0.650x, so the current evidence does not support a universal
Spine energy advantage.

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

## Frozen evidence

The reviewable evidence directory is
`docs/evidence/shared_comparison_sparse_full_20260725/`:

- `comparison_manifest.json` freezes all 146 summary rows, 73 pairs, source
  manifest hash, simulator/plugin/profile hashes, and completion status;
- `analysis/` contains all fail-closed CSV outputs and the analysis manifest;
- `raw_json.tar.gz` contains every child result/manifest/summary and every
  instantiated-channel DRAMSim3 JSON. Text logs are deliberately excluded;
- `SHA256SUMS` pins every frozen artifact.

The raw archive is deterministic. Recreate it after a complete run with:

```bash
tar --sort=name --mtime=@0 --owner=0 --group=0 --numeric-owner \
  --exclude=*.txt --exclude=*.log \
  -czf docs/evidence/shared_comparison_sparse_full_20260725/raw_json.tar.gz \
  -C results shared_comparison_sparse_full_20260725
```

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

An aggregate performance conclusion is valid only for the normalized,
conversion-free profiles frozen by these manifests. Native HLS-aligned and
projected results require separate matrices and labels.
