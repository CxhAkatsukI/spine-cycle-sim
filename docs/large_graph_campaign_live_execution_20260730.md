# Large-graph publication campaign live execution (2026-07-30)

## Frozen inputs

- Contract: `configs/contracts/large_graph_publication_campaign_fullgraph_v3.json`
- Native plugin: `/data/tmp/chuxiao/fullgraph-v8-repair-native-build-20260730/libspine_cycle.so`
- Plugin SHA-256: `eee35f39c118538da5565e497d29b989e5bb492c1368839d424a984c32e2aae9`
- Materialized workloads: `/data/tmp/chuxiao/large_graph_campaign_v1/workloads/`
- Runtime root: `/data/tmp/chuxiao/large_graph_campaign_v1/`

The v3 contract keeps full-graph insertion, freezes Full PageRank at a 4M-edge
cap, and labels weighted-SSSP delete/weight-change as bounded 64K real-topology
tests because the current Spine maintenance launch has
`MAX_SORT_EDGES=131072`.

## Active waves

| Wave | Purpose | Jobs | CPU pool |
|---|---|---:|---|
| `fullgraph_v2_repair` | Full-graph-addressing repair evidence | 2 running, 6 queued | legacy launcher |
| `formal_v3_weighted_wave` | AU and WikiTalk weighted-SSSP E2E | 6 | repinned audit pool |
| `formal_v3_wiki_cc_k1` | Missing WikiTalk CC K1 row | 1 | repinned audit pool |
| `formal_v3_superuser_weighted` | SuperUser weighted-SSSP E2E | 3 | repinned audit pool |
| `formal_v3_superuser_spine_fullpr` | Missing SuperUser Spine Full PageRank row | 1 | repinned audit pool |
| `formal_v3_au_grasu_nonmonotonic` | GraSU delete/weight-change, u1/u8/u64 | 12 | 16-27 |
| `formal_v3_au_spine_weight_remaining` | Spine weight-change u8/u64 | 2 | 28-29 |
| `formal_v3_au_insert_endpoints` | Insert u1/u64 across three systems | 6 | 30-35 |
| `formal_v3_r19_spine` | R19-32 endpoint, four Spine algorithms | 4 | 36-39 |
| `formal_v3_r19_grasu_fullpr` | R19-32 Full PageRank, GraSU+ReGraph K1/K4-shared | 2 | 40-41 |

The v3 launchers use a 112 GiB admission reserve, 96 GiB emergency threshold,
112 GiB recovery threshold, one start per five-second sample, and no automatic
wall-time timeout. The memory circuit breaker soft-stops the fewest high-RSS
jobs needed to recover before host OOM.

## CPU-affinity correction

Multiple independent launchers initially selected the same first physical CPU.
At 2026-07-30 01:30 Asia/Shanghai, the remaining jobs were repinned to distinct
physical CPUs. The machine-readable before/after evidence is:

`/data/tmp/chuxiao/large_graph_campaign_v1/host_affinity_repair_20260730T0125.json`

Simulated cycles, correctness, memory traffic, and energy activity are not
affected by host CPU contention. Host wall time before the correction is
contaminated and must not be used as simulator-throughput evidence. A later
contention-controlled rerun is required for host-runtime claims.

## Monitoring

One-shot summary:

```bash
cd /home/chuxiao/spine-cycle-sim-publication
scripts/monitor_active_publication_campaigns.sh --once
```

Interactive refresh:

```bash
watch -n 2 scripts/monitor_active_publication_campaigns.sh --once
```

Persistent one-minute log:

```bash
tail -f /data/tmp/chuxiao/large_graph_campaign_v1/active_campaign_monitor.log
```

## Live analysis

Refresh all correctness-gated outputs:

```bash
scripts/analyze_active_publication_campaigns.sh
```

The output directory is
`/data/tmp/chuxiao/large_graph_campaign_v1/live_publication_analysis/` and
contains `summary.json`, `system_rows.csv`, `pair_rows.csv`, and
`correctness_groups.csv`. A tmux worker named `spine-v3-live-analysis` refreshes
these files every five minutes. `PARTIAL` is expected until every execution ID
listed by the active manifests has a passing case result.

At the first live snapshot, 38 passing executions and 14 complete
Spine-versus-competitor pairs were observed. Missing or failed executions are
never admitted to pair rows.

R19-32 GraSU admission uses the corrected PMA/oracle RSS envelope. The frozen
endpoint estimates are approximately 13.7 GiB for Full PageRank, 46-47 GiB for
Weighted SSSP and Residual PageRank, and the 64 GiB per-run cap for CC. Those
jobs must run in separate memory-controlled waves; the 12-job R19 endpoint must
not be launched as one concurrent group.

The first R19-32 Spine residual-PageRank insertion completed correctly but had
an empty initial frontier (`initial_active_vertices=0`). It is retained as
evidence for the no-propagation update path, not as the representative
propagating residual-PageRank endpoint. A separately selected update that
crosses the per-vertex activation threshold is required for that claim.
