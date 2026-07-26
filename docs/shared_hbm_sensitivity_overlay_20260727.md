# Shared HBM sensitivity overlay

Date: 2026-07-27

Branch: `codex/scheduler-phase-dispatch`

## Contract

`scripts/run_shared_comparison_matrix.py --dram-config <INI>` now selects one
DRAMSim3 configuration for both normalized Spine and GraSU + ReGraph. The
runner passes the resolved path through `CANDIDATE10_SST_DRAM_CONFIG`; both SST
topologies reject a missing file and bind every instantiated pseudo-channel to
that same configuration.

The selected file is content-hashed into:

- the simulation implementation fingerprint;
- every row's resume key;
- the parent comparison manifest.

The frozen baseline SHA-256 is
`d1e865c6528acbc41f0768667063702bfb4033f24bcd46119ad25bfc5ad4fb5f`.
Any other content is labeled `hbm_sensitivity`; it cannot silently replace a
baseline result. The architecture profile, AXI parameters, FIFO depths, HBM
channel mapping, and workload stay frozen.

## Baseline smoke

```bash
cd /home/chuxiao/spine-cycle-sim-runtime
python3 scripts/run_shared_comparison_matrix.py \
  --manifest configs/experiments/shared_comparison_candidate10_hls_v3_20260726.json \
  --out-dir /data/tmp/chuxiao/shared_hbm_overlay_smoke_20260727 \
  --limit 1 --jobs 2 --timeout-seconds 300 \
  --claim-scope structural_exploratory --no-build \
  --lib-dir /home/chuxiao/spine-cycle-sim-runtime/build/sst \
  --dram-config configs/memory/HBM2_1ch_x128.ini
```

The `syn_chain_v64` weighted-SSSP pair passed all correctness and memory
closure gates:

| System | Cycles |
| --- | ---: |
| Spine | 619,131 |
| GraSU + ReGraph | 2,246,425 |

The parent manifest labels this as
`filtered_candidate10_derived_normalized_structural_subset` and records the
frozen config hash.

## High-latency penetration smoke

A temporary config changed only `CL`, `tRCDRD`, `tRCDWR`, and `tRP` from 14 to
17. The same pair remained correct and closed:

| System | Baseline cycles | High-latency cycles | Change |
| --- | ---: | ---: | ---: |
| Spine | 619,131 | 647,916 | +4.65% |
| GraSU + ReGraph | 2,246,425 | 2,254,290 | +0.35% |

The sensitivity manifest is under
`/data/tmp/chuxiao/shared_hbm_overlay_latency_high_smoke_20260727`. It records
config SHA-256
`161f3696308e21c1ae1d83b09a1ec1ca3ae888c63b3bc519dad47309fed1b53d`
and labels the result
`filtered_candidate10_derived_normalized_hbm_sensitivity_subset`.

This smoke proves parameter penetration, not ranking robustness. The formal
sensitivity matrix must use committed low/high latency and bandwidth configs,
multiple topology/algorithm groups, and report any rank inversion.

## Frozen sensitivity assets

The reproducible profile set is defined by
`configs/memory/hbm_sensitivity_profiles_v1.json` and generated with:

```bash
cd /home/chuxiao/spine-cycle-sim-runtime
python3 scripts/generate_hbm_sensitivity_configs.py
python3 scripts/generate_hbm_sensitivity_configs.py --check
```

The four generated configs are:

| Profile | Changed DRAMSim3 fields |
| --- | --- |
| `latency_low` | `CL/CWL/tRCDRD/tRCDWR/tRP = 11/3/11/11/11` |
| `latency_high` | `CL/CWL/tRCDRD/tRCDWR/tRP = 17/5/17/17/17` |
| `bandwidth_high` | `tCCD_L = 1` |
| `bandwidth_low` | `tCCD_S/tCCD_L = 2/4` |

All four were parsed and executed by DRAMSim3 on the same weighted-chain Spine
smoke. The resulting cycles were 618,454, 647,916, 619,131, and 619,131,
respectively. The bandwidth overlays intentionally have no effect on this
serial chain: a formal bandwidth sensitivity run must include spread, fan-in,
and hub workloads with enough concurrent column commands to expose `tCCD`.

## Frozen sweep

`configs/experiments/candidate10_hbm_sensitivity_matrix_v1.json` selects 12
disjoint calibration, holdout, and validation runs. It covers all three
headline algorithms plus dynamic weighted SSSP, and includes chain, source/dest
hub, spread, bank-fanin, mixed-update, residual-skew, and a real Amazon compact
slice.

Run the complete baseline plus four sensitivity profiles with:

```bash
cd /home/chuxiao/spine-cycle-sim-runtime
python3 scripts/run_shared_hbm_sensitivity.py \
  --out-dir /data/tmp/chuxiao/candidate10_hbm_sensitivity_v1 \
  --jobs 2 --timeout-seconds 1800 --resume --no-build \
  --lib-dir /home/chuxiao/spine-cycle-sim-runtime/build/sst
```

For an incremental profile run, `--profile-id latency_high` automatically
includes the baseline. `--analyze-only` rebuilds the summary from existing
submatrices without launching SST.

The runner writes `sensitivity_details.csv` with per-system cycle ratios,
baseline/sensitivity winners, and strict rank inversions. The group summary
reports geometric-mean Spine speedup and inversion counts for each profile. A
winner is treated as tied inside a 1% ratio band, preventing a negligible
near-1.0 change from being reported as an architectural reversal.
