# Formal-v6 large-graph SSSP wall-time feasibility (2026-07-30)

This audit decides whether a full-graph K4-shared weighted-SSSP execution can
finish inside the frozen 3-hour campaign budget. It is host-runtime evidence,
not an accelerator-cycle result. Partial runs never enter architecture
performance aggregates.

## Reproduction

```bash
cd /home/chuxiao/spine-cycle-sim-publication
python3 scripts/project_formal_v6_sssp_runtime.py \
  --campaign-root /data/tmp/chuxiao/large_graph_campaign_v1 \
  --wall-budget-hours 3 \
  --out docs/evidence/formal_v6_large_sssp_runtime_projection_20260730.json
```

The model uses the median device cycles per directed-edge round from three
completed, dual-oracle-admitted K4-shared runs:

| Dataset | Directed records | Supersteps | Device cycles | Cycles/edge-round |
| --- | ---: | ---: | ---: | ---: |
| AskUbuntu | 390,847 | 14 | 179,053,544 | 32.72 |
| SuperUser | 616,118 | 14 | 291,909,003 | 33.84 |
| WikiTalk | 1,142,352 | 1 | 64,837,217 | 56.76 |

The median coefficient is 33.84 cycles per directed-edge round. The target
superstep counts come from the validated host oracle captured in the frozen SST
launch environment, not from a guessed graph-diameter constant.

## Decision evidence

| Dataset | Directed records | Oracle steps | Observed partial cycles | Observed wall time | Projected total | Extreme optimistic remaining |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| StackOverflow | 23,724,166 | 13 | 338,550,975 | 3.43 h | 105.7 h | 3.57 h |
| Pokec | 44,603,928 | 19 | 59,311,794 | 0.71 h | 342.2 h | 16.76 h |

The extreme optimistic column assumes ten times less remaining work and twice
the observed simulator rate. It still exceeds the 3-hour budget for both
targets. The executions were therefore soft-stopped with their progress and
peak RSS retained in the campaign event logs. StackOverflow reached 338.6 M
cycles and 120.0 M backend requests with a 50.7 GB peak RSS; Pokec reached
59.3 M cycles and 18.3 M requests with a 28.6 GB peak RSS.

## Preflight boundary

The weighted GraSU+ReGraph runner supports a host-only preflight that validates
the old graph, update, exact oracle state, source, partition occupancy, and
minimum supersteps before SST starts:

```bash
python3 scripts/run_sst_grasu_regraph_hls_weighted.py \
  <NORMAL REQUIRED ARGUMENTS> \
  --preflight-only --no-build
```

This writes `preflight.json` with
`claim_class=validated_host_oracle_preflight_not_simulated_performance`. It is
valid input to a wall-time admission decision, but it is never a substitute for
a completed cycle-level execution.

The legacy `scripts/resume_formal_v6_sssp_after_priority.sh` now fails closed
while this projection marks the targets infeasible. An intentional override
requires `SPINE_ALLOW_WALL_TIME_INFEASIBLE=1`; routine campaigns should instead
use preflight evidence to build an explicit feasible allowlist.
