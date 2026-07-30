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

The CC/residual scheduler uses a 128 GiB memory reserve. This allows the
AU/SU/WikiTalk jobs to run alongside SSSP while preventing its 64 GiB
StackOverflow jobs from launching when the two independent schedulers could
otherwise cross the host safety reserve together.

The optional `formal_v6_au_spine_updates` scheduler fills otherwise idle CPU
capacity with the nine AskUbuntu weighted-SSSP update cases: insertion,
deletion, and weight change at batch sizes 1, 8, and 64. It uses a 112 GiB
reserve and therefore yields to the primary campaigns before host memory can
enter the 96 GiB emergency region. Non-monotonic SSSP rows use the contract's
explicit 64K-edge cap; insertion rows use the full materialized graph.

The focused tests prove `Spine < K4-shared < K1` within a workload bucket and
prove that the system offset cannot invert adjacent workload priorities.

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
