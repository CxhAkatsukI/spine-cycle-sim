# Formal-v7 source-matched large-graph SSSP preflights

This evidence upgrades the LiveJournal (`LJ`) and LJournal2008 (`LJ08`)
GraSU+ReGraph K4-shared rows from source-independent one-round admission screens
to source-matched total-cycle projections. The corresponding Spine executions
use the `median_degree` source cohort, so the preflights bind LJ to external
source 71 and LJ08 to external source 26.

## Reproduction

Run each preflight serially. A single run can peak above 60 GiB RSS; running
both together crossed the frozen 64 GiB available-memory reserve and was
stopped before OOM.

```bash
cd /home/chuxiao/spine-cycle-sim-publication

python3 scripts/run_publication_case.py \
  --materialization-manifest \
    /data/tmp/chuxiao/large_graph_campaign_v1/workloads/soc_livejournal1/materialization_manifest.json \
  --system grasu_regraph_k4_shared \
  --algorithm weighted_sssp \
  --scenario insert \
  --batch-size 8 \
  --out-dir \
    /data/tmp/chuxiao/large_graph_campaign_v1/formal_v7_lj_k4_preflight_20260731 \
  --contract configs/contracts/large_graph_publication_campaign_fullgraph_v7.json \
  --sst /data/feiyang/sst/bin/sst \
  --lib-dir /data/tmp/chuxiao/spine-skip-fit-hot-native-20260730 \
  --capability-catalog \
    configs/contracts/grasu_regraph_full_graph_capabilities_v7.json \
  --max-cycles 10000000000000 \
  --source-cohort median_degree \
  --full-pagerank-edge-cap 4000000 \
  --nonmonotonic-sssp-edge-cap 64000 \
  --logical-view main_e2e \
  --preflight-only

python3 scripts/run_publication_case.py \
  --materialization-manifest \
    /data/tmp/chuxiao/large_graph_campaign_v1/workloads/ljournal_2008/materialization_manifest.json \
  --system grasu_regraph_k4_shared \
  --algorithm weighted_sssp \
  --scenario insert \
  --batch-size 8 \
  --out-dir \
    /data/tmp/chuxiao/large_graph_campaign_v1/formal_v7_lj08_k4_preflight_v2_20260731 \
  --contract configs/contracts/large_graph_publication_campaign_fullgraph_v7.json \
  --sst /data/feiyang/sst/bin/sst \
  --lib-dir /data/tmp/chuxiao/spine-skip-fit-hot-native-20260730 \
  --capability-catalog \
    configs/contracts/grasu_regraph_full_graph_capabilities_v7.json \
  --max-cycles 10000000000000 \
  --source-cohort median_degree \
  --full-pagerank-edge-cap 4000000 \
  --nonmonotonic-sssp-edge-cap 64000 \
  --logical-view main_e2e \
  --preflight-only
```

Generate the projection ledger:

```bash
python3 scripts/project_formal_v6_sssp_runtime.py \
  --campaign-root /data/tmp/chuxiao/large_graph_campaign_v1 \
  --wall-budget-hours 3 \
  --r19-preflight \
    /data/tmp/chuxiao/large_graph_campaign_v1/formal_v6_r19_k4_preflight_20260730/preflight.json \
  --additional-preflight \
    /data/tmp/chuxiao/large_graph_campaign_v1/formal_v7_lj_k4_preflight_20260731/preflight.json \
  --additional-preflight \
    /data/tmp/chuxiao/large_graph_campaign_v1/formal_v7_lj08_k4_preflight_v2_20260731/preflight.json \
  --out docs/evidence/formal_v7_large_sssp_runtime_projection_20260731.json
```

## Results

| Dataset | Source | Directed records | Oracle supersteps | Projected cycles | Projected host time |
| --- | ---: | ---: | ---: | ---: | ---: |
| LJ | 71 | 85,702,474 | 27 | 78,309,180,683 | 789.2 h |
| LJ08 | 26 | 99,028,542 | 35 | 117,296,211,780 | 1,182.1 h |

The projection is

```text
median completed cycles/(edge*superstep)
  * directed records
  * validated oracle-minimum supersteps.
```

The coefficient is fitted only from correctness-admitted completed K4-shared
runs. The preflight validates the graph and update hashes, source, exact host
oracle, selected supersteps, and partition occupancy without launching SST.

## Claim boundary

These are source-matched total-cycle feasibility projections, not completed
cycle simulations and not measured speedups. They may be plotted as projected
timeout bars, but they remain excluded from measured cross-architecture
aggregates. The host-time values estimate the cost of running the current
simulator and are not accelerator latency.

The weighted host oracle now computes exact distances and shortest-path hop
depth in one Dijkstra traversal. Focused weighted-runner and report tests prove
the refactor preserves distances and required supersteps on the existing
fixture matrix.
