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
commit 05584da feat: stream sparse carry cursors
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
PAGE_CSR_VERTICES_PER_PAGE = 256
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

After the Phase 1 maintenance update, old v0 cycle tables are obsolete. The
suite should be regenerated when comparing against hw/hw_emu because B-stage
maintenance now contributes explicit `sorted_edges` scan and sparse-carry
cycles.

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

Run maintenance-focused microbenchmarks:

```bash
cd /home/chuxiao/spine-cycle-sim
python3 scripts/run_maintenance_microbench.py \
  --out-dir results/maintenance_phase1_microbench
```

Observed Phase 1 microbench summary:

| case | status | cycles | maintenance cycles | scan passes | max target | interpretation |
| --- | --- | ---: | ---: | ---: | ---: | --- |
| `cold_l0_store_one_family` | PASS | 494 | 69 | 6 | 0 | L0 store includes diagnostic scan, all-family pre-count, and one write scan. |
| `balanced_l1_cascade` | PASS | 1921 | 1488 | 14 | 1 | Balanced two-batch update stores L0 then carries to L1 with cursor work. |
| `concentrated_l1_overflow` | FAIL | 24 | 133 | 6 | 0 | Concentrated second batch fails L1 family capacity; failure includes `maintenance_path=cascade`. |
| `duplicate_l0_coalesce` | PASS | 521 | 64 | 3 | 0 | Raw duplicate input edges collapse to one L0 output edge. |
| `hot_zero_input_group_scans` | PASS | 3493 | 2700 | 53 | 2 | Hot metadata causes cold/hot group scans; zero-input groups can still carry old data. |

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
case,workload,vertices,edges,capacity_status,cycles,simulated_time_ms,edges_per_second,carry_count,maintenance_event_count,maintenance_store_l0_events,maintenance_cascade_events,maintenance_estimated_cycles,maintenance_scan_passes,maintenance_scan_cycles,maintenance_max_target_level,hbm_request_count,fifo_stall_cycles,memory_stall_cycles,compute_stall_cycles,sssp_iterations,tiny_active_iterations,hot_enabled,hot_edges,cold_edges,hot_vertex_count
cli_chain_1024,chain,1024,1023,PASS,23083,0.17226119402985074,5938656.153879479,0,1,1,0,20480,18,18414,0,2,0,528,0,1024,1024,False,0,1023,0
```

## Current Interpretation

This simulator should be read as a cycle-level architecture model, not as a
cycle-exact RTL substitute. The validation target is trend agreement:

- HLS-style `sorted_edges` multi-pass maintenance is now represented in the
  B-stage timing model.
- balanced ratio-2 carry fits
- concentrated incremental updates fail at the same low-level family-capacity boundary
- low-diameter concentrated graphs expose family pressure
- high-diameter chain behavior is separated from storage pressure and visible in
  SSSP iteration statistics
- hot/cold is a graph-scale preload classifier for skewed graphs; the exact raw
  RMAT-24-9 result is validated by the newest HW evidence and represented in
  the model as classifier/family-capacity behavior rather than by expanding
  150,994,944 Python edge objects in the default suite

For overflow microbenchmarks, use the failure metadata to diagnose the boundary.
The current simulator detects a failed target-family capacity check before it
schedules the failed event's full scan/carry latency, so failed-run cycles are
not hardware-cycle evidence.
