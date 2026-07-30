# Large-graph campaign launch order

## Policy

Formal campaign manifests assign deterministic launch priority in this order for
the same workload-size bucket:

1. Spine
2. GraSU + ReGraph K4-shared
3. GraSU + ReGraph K1

K4-shared is the strongest resource-feasible GraSU baseline and therefore runs
before the slower K1 diagnostic. K1 remains in the frozen matrix and is not
removed from correctness, scaling, or performance evidence.

The priority affects scheduling only. It does not alter graph inputs, update
batches, architecture profiles, simulator timing, correctness gates, or result
analysis. Workload priority remains dominant, so a lower-priority system for an
earlier workload-size bucket still starts before any system in the next bucket.

## Running campaigns

Manifests already in flight are immutable because the campaign state records the
manifest hash. Their running K1 jobs are allowed to finish when memory remains
safe; future generated manifests use the launch order above. This preserves the
audit trail and avoids discarding already invested simulation time.

## Reproduction

```bash
cd /home/chuxiao/spine-cycle-sim-publication
python3 -m unittest tests.test_large_graph_campaign
python3 -m unittest discover -s tests
```

Monitor the current v6 SSSP and CC/residual campaigns together:

```bash
cd /home/chuxiao/spine-cycle-sim-publication
bash scripts/monitor_formal_v6_campaigns.sh
```

Refresh their correctness-gated analyses independently so that the v6 warm
SSSP measurement window is not mixed with v3/v4/v5 rows:

```bash
bash scripts/analyze_formal_v6_campaign.sh
SPINE_V6_CAMPAIGN_DIR=/data/tmp/chuxiao/large_graph_campaign_v1/formal_v6_cc_residual_priority \
SPINE_V6_ANALYSIS_DIR=/data/tmp/chuxiao/large_graph_campaign_v1/formal_v6_cc_residual_priority/analysis \
  bash scripts/analyze_formal_v6_campaign.sh
bash scripts/analyze_formal_v6_primary.sh
```

Refresh the two analyses and the deterministic publication PDF in one step:

```bash
bash scripts/refresh_formal_v6_report.sh
```

The script uses `/data/tmp/chuxiao/spine-paper-plot-venv/bin/python` by
default and accepts `SPINE_PLOT_PYTHON` as an override. It freezes
`SOURCE_DATE_EPOCH` so unchanged inputs reproduce identical vector figures
and report PDF bytes.

The CC/residual scheduler uses a 112 GiB launch/recovery reserve and a 96 GiB
emergency stop threshold. This allows the measured-small AU/SU/WikiTalk jobs
to run alongside SSSP while the predictor continues to hold its large
StackOverflow jobs when the two independent schedulers could otherwise cross
the host safety reserve together.

On July 30, two queued jobs were moved to one-job sidecar schedulers when their
RSS estimates fit safely beside the active jobs: the 8.81 GiB WikiTalk
K4-shared residual-PageRank job uses
`formal_v6_wiki_residual_k4_sidecar`, and the 17.38 GiB StackOverflow Spine CC
job uses `formal_v6_stackoverflow_spine_cc_sidecar`. The original scheduler
records auditable `stopped` rows with reason
`moved to memory-bounded sidecar for safe fourth-task concurrency`; the
sidecars use the exact original commands and output directories, a 96 GiB launch
reserve, and a 64/80 GiB emergency/recovery circuit breaker. This changes only
dispatch ownership. The dataset, update, architecture profile, plugin,
correctness gates, and result path are unchanged, and the unified monitor
shows both schedulers.

After the CC and residual sidecars completed, the 64 GiB-estimated soc-Pokec
K4-shared SSSP execution was transferred from `formal_v6_sssp_exact` to
`formal_v6_pokec_sssp_k4_sidecar`. At transfer time the host had 136.8 GiB
available, so a full 64 GiB estimate still left more than the sidecar's 48 GiB
emergency threshold. The original queue entry records the ownership-transfer
reason; the sidecar retains the original command and result path and uses a
64 GiB launch reserve with a 48/64 GiB emergency/recovery circuit breaker.
The separately queued R19 K4 dispatcher remains paused while this real-dataset
execution owns the additional memory slot.

The `formal_v6_r19_sssp_warm` campaign adds the separately reported R19-32
synthetic scalability endpoint under the same v6 warm-start measurement
contract and median-degree source policy. Its one-job scheduler uses a 108 GiB
launch reserve: the 7.60 GiB Spine row may fill a safe gap, while the 46.55 GiB
K4-shared row remains queued until the larger real-graph jobs release enough
memory. R19 is included in formal execution coverage but remains visually
separated from the real-dataset results.

The optional `formal_v6_au_spine_updates_default` scheduler fills otherwise idle CPU
capacity with the nine AskUbuntu weighted-SSSP update cases: insertion,
deletion, and weight change at batch sizes 1, 8, and 64. It uses a 112 GiB
reserve and therefore yields to the primary campaigns before host memory can
enter the 96 GiB emergency region. Non-monotonic SSSP rows use the contract's
explicit 64K-edge cap; insertion rows use the full materialized graph. Its
manifest records `source_cohort_override=default` so that the v6 Spine rows
can be paired with the correctness-passing v3 K4-shared rows without changing
the graph, source, update, or algorithm parameters.

The update analyzer enforces that provenance with system-filtered roots: it
loads Spine only from the v6 campaign and loads K1/K4-shared only from the
listed v3 campaigns. The resulting `summary.json` records this selection. An
unfiltered old Spine row with the same scientific execution ID remains a hard
duplicate-result error rather than being silently preferred or overwritten.

The focused tests prove `Spine < K4-shared < K1` within a workload bucket and
prove that the system offset cannot invert adjacent workload priorities.

## Weighted-SSSP host oracle compaction

The weighted GraSU+ReGraph runner compacts its correctness oracle immediately
before launching SST. The compact form retains the external/internal vertex
maps, final distances, minimum supersteps, and per-partition maximum source,
then releases the parsed graph and duplicate external/internal edge tuples.
This is a host-memory optimization only: it does not alter the SST component,
architecture profile, cycle scheduler, memory requests, or DRAM backend.

An exact smoke A/B used the same profile, workload, update, and immutable
plugin (`96b4375...`). Original and compact runs both produced 168,009 cycles,
67,664 backend requests, and byte-identical `result`, `oracle`, and `dram`
objects. New manifests record
`host_oracle_storage=compacted_before_sst_launch_v1`. Already-running jobs keep
their original process image; only subsequently launched weighted-SSSP jobs
use the compact host representation.

## Arbitration admission found during monitoring

The first AU K4-shared residual run completed simulation but exposed an
over-constrained parent admission check. The check required arbitration intents
to equal accepted HBM requests. With the 23-pseudo-channel physical mapper,
multiple logical channels can contend for one physical channel, so a granted
reservation attempt can be retried when that physical channel has consumed its
same-cycle acceptance or outstanding capacity.

The corrected admission keeps two strict ledgers:

- arbitration: `unique_intents == grants == consumed_grants`, with no pending
  intents or grants;
- memory: accepted backend requests equal backend traffic, DRAM completions,
  and the algorithm-specific expected request count.

It additionally requires `unique_intents >= backend_requests`; a request that
reached HBM without a corresponding arbitration intent remains fatal. The CSV
row records both `backend_arbitration_unique_intents` and the derived retried
intent count. This changes evidence admission only, not simulated timing.
