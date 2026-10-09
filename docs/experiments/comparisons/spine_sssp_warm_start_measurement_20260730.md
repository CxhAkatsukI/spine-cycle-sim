# Spine Dynamic SSSP Warm-Start Measurement

## Purpose

Publication dynamic-update latency must exclude construction of the initial
graph and the initial SSSP solution. The old runner reported both the cold
prefix and the incremental update in `cycles`, even though it also exported
`cold_cycles` and `update_cycles`. That made a dynamic update appear hundreds
of times slower than its measured update window.

The warm-start path now installs the independently computed old-graph SSSP
state and resident Spine graph layout without advancing simulated time. It
then activates the update sources and uses the normal execution-driven
maintenance, reader, compute, AXI, FIFO, and HBM paths. Only positive insertion
updates use this path. Delete and weight-increase cases retain their explicit
full-rebuild fallback contract.

## Formal Equivalence Check

The check uses the AskUbuntu directed slice with 515,281 vertices, 390,847
edges, source 15,811, and an eight-edge insertion. The cold and warm runs use
the same graph, update, architecture profile, plugin, SST, and DRAM model.

| Metric | Cold execution | Warm execution |
|---|---:|---:|
| Timed cold cycles | 24,856,668 | 0 |
| Dynamic cycles | 62,336 | 62,331 |
| Dynamic HBM requests | 3,482 | 3,482 |
| Total cycles | 24,919,004 | 62,331 |
| Correctness mismatches | 0 | 0 |
| Final value SHA-256 | `9cf4053e...3465a6` | `9cf4053e...3465a6` |

The dynamic cycle difference is five cycles, or 0.0081%. The HBM request
ledger and final SSSP vector are exact matches. The small schedule difference
comes from entering maintenance with a preinstalled resident state rather than
after a timed cold round; it does not change realized work or the result.

Compact evidence is tracked in
`docs/evidence/spine_sssp_warm_start_askubuntu_20260730.json`.

## Reproduction

Build the plugin:

```bash
cd /home/chuxiao/spine-cycle-sim-publication
cmake -S . -B /data/tmp/chuxiao/spine-warm-start-native-build-20260730 \
  -DSPINE_BUILD_SST=ON \
  -DSST_CONFIG=/data/feiyang/sst/bin/sst-config \
  -DSPINE_DRAMSIM3_SOURCE_DIR=/data/tmp/chuxiao/candidate73-dramsim3-pgo-src-20260729
cmake --build /data/tmp/chuxiao/spine-warm-start-native-build-20260730 -j
```

Common arguments:

```bash
COMMON="--sst /data/feiyang/sst/bin/sst \
--lib-dir /data/tmp/chuxiao/spine-warm-start-native-build-20260730 --no-build \
--scenario dynamic_sssp --validation-mode generic \
--profile configs/architectures/spine_candidate10_opt_v2_reader_working_set.json \
--workload /data/tmp/chuxiao/large_graph_campaign_v1/workloads/sx_askubuntu/graphs/directed_weighted.slice \
--update-workload /data/tmp/chuxiao/large_graph_campaign_v1/workloads/sx_askubuntu/updates/directed/insert_u8.slice \
--source 15811 --max-cycles 10000000000000 --max-rounds 4096"
```

Run the timed cold prefix and warm update window:

```bash
python3 scripts/run_sst_spine_vertical.py \
  --out-dir /data/tmp/chuxiao/spine-warm-start-equivalence-20260730/askubuntu_cold \
  $COMMON
python3 scripts/run_sst_spine_vertical.py \
  --out-dir /data/tmp/chuxiao/spine-warm-start-equivalence-20260730/askubuntu_warm \
  $COMMON --sssp-warm-start
```

Publication case construction now adds `--sssp-warm-start` for Spine positive
incremental SSSP, validates `cycles == update_cycles`, and reports only the
dynamic backend traffic. Raw cold-prefix fields remain available for audit.

## Verification

```bash
cd /home/chuxiao/spine-cycle-sim-publication
python3 -m unittest -q \
  tests.test_shared_comparison_runner \
  tests.test_publication_analysis \
  tests.test_publication_case_runner \
  tests.test_publication_cases \
  tests.test_sst_spine_vertical
git diff --check
```
