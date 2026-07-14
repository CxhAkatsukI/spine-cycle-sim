# Validation Against Spine HW Evidence

This document records the first trend-validation target for the Spine v0 cycle
simulator.

## Evidence Used

Spine real-hw evidence:

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

## Hardware Facts Captured By The Model

```text
HOST_PARTITIONED_RATIO2_MAX_SORT_N = 131072
HOST_PARTITIONED_CSR_DST_PARTITIONS = 16
L0 capacity per partition = 131072
L1 total capacity = 262144
L1 capacity per partition = 16384
```

The simulator default config is:

```text
configs/spine_current.yaml
```

## Expected Trend Checks

The first simulator version must reproduce these qualitative conclusions:

| case | HW evidence | expected simulator trend |
| --- | --- | --- |
| `small_chain_v64` | Spine wins versus GraSU+ReGraph on tiny high-diameter chain | PASS with low storage pressure |
| `small_star/spread/hotdst` | valid FITS comparison cases, but Spine is slower than GraSU+ReGraph | PASS, with concentrated partition pressure visible |
| balanced `131072+1` | split edge-file balanced probe passes | PASS, L1 max partition load around 8193 |
| one-partition `131072+1` | split edge-file one-partition probe fails | FAIL with `level_partition_capacity` at L1 partition 0 |
| large low-diameter concentrated cases | current Spine layout unsupported | FAIL once L1 partition capacity is exceeded |

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
| `small_chain_v64` | PASS | 543 | 0 | 32 | 64 | High-diameter behavior appears as many SSSP iterations. |
| `small_star_v4096_u1024` | PASS | 2654 | 0 | 2 | 2 | Low-diameter, concentrated partition pressure is visible without capacity failure at this size. |
| `small_spread_v4096_u1024` | PASS | 1694 | 0 | 2 | 2 | Low-diameter one-partition distribution remains a pressure case. |
| `small_hotdst_v4096_u1024` | PASS | 1630 | 0 | 2 | 1 | Hot destination has low SSSP propagation cost but concentrated storage pressure. |
| `balanced_full_plus_one` | PASS | 144802 | 1 | 48 | 1 | Reproduces the balanced `131072+1` carry pass. |
| `one_partition_full_plus_one` | FAIL | 131079 | 1 | 1 | 0 | Reproduces L1 partition capacity failure. |
| `large_chain_v4096` | PASS | 8700 | 0 | 32 | 4096 | Large high-diameter behavior appears as many SSSP iterations. |
| `large_star_v1048576_u65536` | FAIL | 262149 | 1 | 1 | 0 | Reproduces concentrated large low-diameter L1 partition capacity failure. |
| `large_spread_v262144_u65536` | FAIL | 262149 | 1 | 1 | 0 | Reproduces concentrated large low-diameter L1 partition capacity failure. |
| `large_hotdst_v262144_u65536` | FAIL | 262149 | 1 | 1 | 0 | Reproduces concentrated large low-diameter L1 partition capacity failure. |
| `random_rmat_small` | PASS | 8132 | 0 | 32 | 7 | Skewed random workload provides a small nonuniform sanity case. |

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
cycle-exact RTL substitute. The first validation target is trend agreement:

- balanced carry fits
- one-partition carry fails at the same L1 partition-capacity boundary
- low-diameter concentrated graphs expose partition pressure
- high-diameter chain behavior is separated from storage pressure and visible in
  SSSP iteration statistics
