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
| `formal_v3_au_spine_weight_u1` | Spine weight-change u1 | 1 | 52 |
| `formal_v3_au_spine_delete` | Spine delete u1/u8/u64 | 3 | 49-51 |
| `formal_v3_au_insert_endpoints` | Insert u1/u64 across three systems | 6 | 30-35 |
| `formal_v3_au_dense_k4` | AU dense insert u512/u4096, Spine and K4-shared | 4 | 53-56 |
| `formal_v3_remaining5_spine_weighted` | Weighted SSSP on five remaining Spine-admitted real graphs | 5 (1 concurrent) | 57 |
| `formal_v3_remaining7_k4_weighted` | Weighted SSSP K4-shared on seven remaining real graphs; paused behind R19-CC | 7 stopped, rerun pending | 58 |
| `formal_v3_r19_spine` | R19-32 endpoint, four Spine algorithms | 4 | 36-39 |
| `formal_v3_r19_grasu_fullpr` | R19-32 Full PageRank, GraSU+ReGraph K1/K4-shared | 2 | 40-41 |
| `formal_v3_r19_k4_priority` | R19-32 K4-shared weighted SSSP PASS; original CC exact-boundary failure retained | 2 (1 concurrent) | 47 |
| `formal_v3_r19_cc_guard` | Corrected R19-32 K4-shared CC formal rerun | 1 | 47 |
| `formal_v3_stackoverflow_spine` | StackOverflow Spine weighted SSSP, CC, residual PageRank | 3 (1 concurrent) | 48 |
| `formal_v3_small_cc_residual` | AU/SU/WikiTalk CC and residual PageRank, three systems | 18 (3 concurrent) | 42-44 |
| `formal_v3_small_fullpr` | AU/SU/WikiTalk Full PageRank, three systems | 9 (2 concurrent) | 45-46 |

The v3 launchers use a 112 GiB admission reserve, 96 GiB emergency threshold,
112 GiB recovery threshold, one start per five-second sample, and no automatic
wall-time timeout. The memory circuit breaker soft-stops the fewest high-RSS
jobs needed to recover before host OOM.

The remaining-real-data K4 wave is a deliberate exception: every job carries
a conservative 64 GiB estimate and only one may run. Its 96 GiB admission
reserve means it waits until at least 160 GiB is available; the 80 GiB
emergency threshold still leaves a large host safety margin. Bitcoin and
UK-2002 exceed Spine's frozen $2^{24}$-vertex admission bound, so their K4 rows
are capacity evidence and cannot form a Spine speedup pair.

The first Bitcoin attempt allocated 31.7 GiB during bootstrap before producing
simulated-cycle progress. It was soft-stopped after 203 seconds so R19-32 CC
could take the single high-memory K4 slot. A five-second launcher race briefly
started Pokec; its process group was terminated before cycle progress and the
entire wave was then closed with an auditable `stop-all` request. R19-32 CC was
resumed with an 88 GiB reserve, 72 GiB emergency threshold, and one-job limit.
The seven real-data K4 rows remain expected-but-missing until a fresh post-R19
wave completes them.

The first R19-32 K4-shared CC run exposed an exact source-window boundary in
ReGraph's one-window-ahead HLS prefetch. The packed address map now reserves the
required 16 KiB source-state guard without suppressing any simulated request.
The original failure remains in `formal_v3_r19_k4_priority`; the corrected run
uses `formal_v3_r19_cc_guard`, an 88 GiB admission reserve, a 72 GiB emergency
threshold, and the same CPU 47 high-memory slot. See
`docs/grasu_regraph_source_prefetch_guard_20260730.md` for the HLS mapping and
boundary validation.

A dependency watcher named `spine-v3-remaining7-k4-after-r19` polls the
corrected campaign state once per minute. It resumes
`formal_v3_remaining7_k4_weighted` only after R19 CC reaches `pass`; a failed or
incomplete dependency terminates the watcher without launching another
high-memory process. The post-R19 wave remains single-job, uses CPU offset 58,
and applies 96/80/96 GiB admission/emergency/recovery thresholds.

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

The per-campaign monitor reports elapsed time, RSS, phase, cycles, memory
requests, and ETA. ETA is derived only for bounded `completed/total` work (for
example fixed-iteration Full PageRank); convergence-driven SSSP/CC reports `-`
instead of extrapolating an unknown number of rounds.

## Live analysis

Refresh all correctness-gated outputs:

```bash
scripts/analyze_active_publication_campaigns.sh
```

The output directory is
`/data/tmp/chuxiao/large_graph_campaign_v1/live_publication_analysis/` and
contains `summary.json`, `system_rows.csv`, `pair_rows.csv`, and
`correctness_groups.csv`. It also emits `component_activity_rows.csv`, which
normalizes workload-specific component cycles, work items, selected array
accesses, backend requests, and stalls while explicitly excluding a total-energy
claim. A tmux worker named `spine-v3-live-analysis` refreshes
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

Live publication aggregation is restricted to the current plugin cohort
(`eee35f39c118538da5565e497d29b989e5bb492c1368839d424a984c32e2aae9`).
The 36 `formal_candidate92_v1` rows use the superseded `88d446...` plugin and
remain available as historical evidence, but are intentionally excluded from
the current aggregate. The analyzer's duplicate-science guard caught this
cohort boundary when current AU CC/residual runs reused the same execution IDs;
the guard remains strict.

The first R19-32 Spine CC attempt failed before useful simulation with
`SST backend request targets an unbound memory channel`. Its 29.7M-record
reciprocal snapshot exceeds one cold family's aggregate fixed-level capacity,
so resident preload automatically promotes high-indegree destinations into
hashed hot shards. The sparse Python binding had considered only cold
destination partitions. The binding now mirrors the fixed-capacity promotion
trigger and includes every promoted hot shard; ordinary slices below the
trigger retain their smaller sparse binding. The failed CC row is not admitted,
and the stopped R19 Full PageRank/SSSP runs are restarted under the corrected
binding while preserving the passing residual fast-path evidence.
