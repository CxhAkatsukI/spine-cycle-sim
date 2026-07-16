# Validation Against Spine HW Evidence

This document records the trend-validation target for the Spine cycle
simulator after updating it to the newest `origin/reduce-levels-for-routing`
source.

## Evidence Used

Older split Spine real-hw evidence:

```text
/home/chuxiao/grasu-regraph-integration/docs/spine_hw_evidence_2026-07-12.md
```

Partition capacity probe:

```text
/home/chuxiao/grasu-regraph-integration/docs/spine_partition_capacity_probe_2026-07-12.md
```

Horizontal comparison summary:

```text
/home/chuxiao/grasu-regraph-integration/docs/spine_vs_grasu_regraph_conclusions_2026-07-12.md
```

Important hardware artifact:

```text
/data/feiyang/spine-dynamic-graph-builds/split_e2e_hw_150_depth32_bram_20260711_2100/xclbin/spine_partitioned_split_e2e.hw.xclbin
sha256 69145517738cc1ffff95e91c24393260c346ac683db9eef2989bbc1bdb7a3469
```

Newest source baseline inspected for this simulator update:

```text
/home/chuxiao/spine-dynamic-graph-reduce-levels
origin/reduce-levels-for-routing
commit cbd3ceb test: validate full-scale skewed RMAT storage
```

Newest raw RMAT hot/cold evidence:

```text
/home/chuxiao/spine-dynamic-graph-reduce-levels/openspec/changes/support-skewed-rmat-hot-cold-storage/validation.md
/home/chuxiao/spine-dynamic-graph-reduce-levels/openspec/changes/support-skewed-rmat-hot-cold-storage/artifacts/validation_20260716/README.md
```

## Hardware Facts Captured By The Model

```text
MAX_N = 16777216
VS_PARTITION_SIZE = 1048576
PARTITIONED_RATIO2_LEVELS = 11
PARTITIONED_RATIO2_LEVEL_SIZE_RATIO = 2
PARTITIONED_RATIO2_MAX_SORT_N = 131072
PARTITIONED_CSR_DST_PARTITIONS = 16
PARTITIONED_HOT_SHARDS = 16
L1 capacity per family = 16384
L10 capacity per family = 8388608
family total capacity = 16891904
```

The simulator default config is:

```text
configs/spine_current.yaml
```

## Expected Trend Checks

The first simulator version must reproduce these qualitative conclusions:

| case | HW evidence | expected simulator trend |
| --- | --- | --- |
| `small_chain_v64` | high-diameter work should appear as many SSSP iterations | PASS with low storage pressure |
| `small_star/spread/hotdst` | small low-diameter updates should fit, but pressure should concentrate in one cold family | PASS with concentrated family pressure visible |
| balanced `131072+1` | balanced split edge-file carry passes | PASS, L1 max family load around 8193 |
| one-family `131072+1` | concentrated incremental update exceeds the L1 binary target | FAIL with `level_family_capacity` at L1 family 0 |
| large low-diameter concentrated incremental updates | current low-level binary carry cannot absorb one-family 262144-edge update | FAIL once L1 family capacity is exceeded |
| raw RMAT-24-9 preload | newest branch stores raw skewed graph via hot/cold family split | model records hot/cold classifier; exact 150,994,944-edge run is taken from HW evidence, not expanded in Python |

## Reproduction

Run the simulator suite:

```bash
cd /home/chuxiao/spine-cycle-sim
python3 scripts/run_spine_suite.py \
  --config configs/spine_current.yaml \
  --out-dir results/spine_v0_suite
```

The current v0 suite result is:

| case | status | cycles | carry | HBM req | SSSP iters | interpretation |
| --- | --- | ---: | ---: | ---: | ---: | --- |
| `small_chain_v64` | PASS | 549 | 0 | 2 | 64 | High-diameter behavior appears as many SSSP iterations. |
| `small_star_v4096_u1024` | PASS | 264734 | 0 | 2 | 2 | Production vertex geometry adds read-maint scan cost; storage fits. |
| `small_spread_v4096_u1024` | PASS | 263982 | 0 | 2 | 3 | Low-diameter one-family distribution remains a pressure case. |
| `small_hotdst_v4096_u1024` | PASS | 263710 | 0 | 2 | 1 | Hot destination has low SSSP propagation cost but concentrated storage pressure. |
| `balanced_full_plus_one` | PASS | 402850 | 1 | 48 | 1 | Reproduces balanced `131072+1` binary carry pass under range partitioning. |
| `one_partition_full_plus_one` | FAIL | 131077 | 0 | 0 | 0 | Reproduces attempted L1 family capacity failure. |
| `large_chain_v4096` | PASS | 9180 | 0 | 2 | 4096 | Large high-diameter behavior appears as many SSSP iterations. |
| `large_star_v1048576_u65536` | FAIL | 262147 | 0 | 1 | 0 | Concentrated incremental update exceeds L1 family capacity. |
| `large_spread_v262144_u65536` | FAIL | 262147 | 0 | 1 | 0 | Concentrated incremental update exceeds L1 family capacity. |
| `large_hotdst_v262144_u65536` | FAIL | 262147 | 0 | 1 | 0 | Concentrated incremental update exceeds L1 family capacity. |
| `random_rmat_small` | PASS | 266827 | 0 | 32 | 2 | Small nonuniform RMAT-like sanity case. |

Result files:

```text
results/spine_v0_suite/*.json
results/spine_v0_suite/*.csv
results/spine_v0_suite/summary.csv
```

Run unit tests:

```bash
cd /home/chuxiao/spine-cycle-sim
python3 -m unittest discover -s tests
```

Clean-environment install check used during this implementation:

```bash
cd /home/chuxiao/spine-cycle-sim
rm -rf /tmp/spine-cycle-sim-venv
python3 -m venv /tmp/spine-cycle-sim-venv
/tmp/spine-cycle-sim-venv/bin/python -m pip install -e .
/tmp/spine-cycle-sim-venv/bin/python -m unittest discover -s tests -v
```

Single CLI smoke used during this implementation:

```bash
cd /home/chuxiao/spine-cycle-sim
python3 scripts/run_spine_sim.py \
  --workload chain \
  --vertices 1024 \
  --edges 1023 \
  --source 0 \
  --config configs/spine_current.yaml \
  --out-dir results/demo_chain \
  --case cli_chain_1024
```

Observed CLI smoke summary:

```text
cli_chain_1024,chain,1024,1023,PASS,2484,0.01656,61775362.31884059,0,32,0,6528,0,1024
```

## Current Interpretation

This simulator should be read as a cycle-level architecture model, not as a
cycle-exact RTL substitute. The validation target is trend agreement:

- balanced ratio-2 carry fits
- concentrated incremental updates fail at the same low-level family-capacity boundary
- low-diameter concentrated graphs expose family pressure
- high-diameter chain behavior is separated from storage pressure and visible in
  SSSP iteration statistics
- hot/cold is a graph-scale preload classifier for skewed graphs; the exact raw
  RMAT-24-9 result is validated by the newest HW evidence and represented in
  the model as classifier/family-capacity behavior rather than by expanding
  150,994,944 Python edge objects in the default suite
