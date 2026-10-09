# Workload-specific component energy evidence

## Method

This analysis combines three independent evidence sources:

1. the cycle simulator supplies exact measured duration and component active
   cycles for each correctness-admitted execution;
2. Vivado post-route hierarchy reports supply component power at 150 MHz;
3. DRAMSim3 supplies HBM-device energy from the exact command stream.

For an FPGA component, energy in microjoules is:

```text
component_energy_uj = routed_power_w * active_cycles / clock_mhz
```

Platform dynamic residual and device static power apply over the full E2E
runtime. DRAMSim3 picojoules are converted to microjoules and added separately.
Every system row closes against the sum of user-logic dynamic, platform
dynamic, device static, and HBM DRAM energy.

The routed hierarchy groups are HBM interface logic, update maintenance,
graph compute, stream/FIFO logic, and other user logic. The current evidence
contains 25 system rows and nine matched Spine versus GraSU+ReGraph K4-shared
pairs across SSSP, CC, and thresholded residual PageRank.

## Current result

The median `GraSU+ReGraph / Spine` total estimated energy ratio is:

| algorithm | pairs | median | range |
| --- | ---: | ---: | ---: |
| weighted SSSP | 3 | 2,367.21x | 1,233.63x to 3,919.99x |
| connected components | 3 | 7.35x | 5.10x to 11.64x |
| residual PageRank | 3 | 9.41x | 6.60x to 14.27x |

The large SSSP ratio is primarily a duration result: the conversion-free
GraSU+ReGraph baseline performs a complete routed ReGraph execution while
Spine starts from persisted graph and algorithm state and propagates the
differential. It must not be interpreted as a thousands-fold instantaneous
power advantage.

## Confidence and proxies

This is a modeled complete accelerator-energy ledger, not board-power
measurement and not RTL-SAIF power simulation. Vivado labels the vectorless
activity confidence as Low. Execution-driven active cycles gate component
duration, but do not reconstruct per-net toggle rates.

Routed-build coverage is explicit:

- Spine weighted SSSP uses its exact routed profile;
- Spine CC and residual PageRank use the Spine SSSP routed profile as a labeled
  algorithm proxy;
- GraSU+ReGraph SSSP and residual PageRank use exact routed profiles;
- GraSU+ReGraph CC uses its SSSP routed profile as a labeled proxy.

This follows Graphicionado's separation between cycle-simulated performance
and implementation-tool PPA evidence, while retaining a lower dynamic-power
confidence than RTL-derived SAIF. CACTI ASIC SRAM projections remain a
separate ledger and are never mixed with FPGA BRAM/URAM power.

## Reproduction

```bash
cd /home/chuxiao/spine-cycle-sim-publication
python3 scripts/analyze_workload_component_energy.py \
  --system-rows /data/tmp/chuxiao/large_graph_campaign_v1/formal_v7_primary_analysis/system_rows.csv \
  --activity-rows /data/tmp/chuxiao/large_graph_campaign_v1/formal_v7_primary_analysis/component_activity_rows.csv \
  --power-rows docs/paper/data/component_power.csv \
  --out-dir docs/paper/data/workload_energy

python3 -m unittest -q tests.test_workload_energy
```

The generated machine-readable files are `system_energy.csv`,
`component_energy.csv`, `pair_energy.csv`, and `workload_energy.json` under
`docs/paper/data/workload_energy`.
