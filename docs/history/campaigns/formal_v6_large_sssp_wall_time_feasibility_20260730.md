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
  --r19-preflight \
    /data/tmp/chuxiao/large_graph_campaign_v1/formal_v6_r19_k4_preflight_20260730/preflight.json \
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
The median completed-run simulator rate is 27,564 device cycles per host second.

For graphs that were never launched, the admission screen deliberately uses
more optimistic assumptions: the smallest completed coefficient (32.72
cycles/edge-round), the largest completed simulator rate (28,726 cycles/s),
and exactly one mandatory full-graph superstep. This is an empirical lower-work
screen, not a cycle simulation or a host-oracle preflight.

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

The separate R19 publication preflight validates source 113, 15,483,485
directed records, 10 required supersteps, and all 8 nonempty destination
partitions. It projects 5.24 billion cycles and 52.8 host hours at the median
completed-run simulator rate, so the K4 cycle simulation was not launched.
The raw preflight is copied to
`docs/evidence/formal_v6_r19_k4_preflight_20260730.json`; it is explicitly not a
performance result.

The four remaining real-graph K4-shared rows are authenticated directly by
their materialization-manifest and directed-graph SHA-256 values. Even under
the optimistic one-round screen, their projected host times are:

| Dataset | Directed records | Minimum rounds used | Projected host time |
| --- | ---: | ---: | ---: |
| LiveJournal | 85,702,474 | 1 | 27.1 h |
| Hollywood | 112,751,422 | 1 | 35.7 h |
| LJournal2008 | 99,028,542 | 1 | 31.3 h |
| Orkut | 234,370,166 | 1 | 74.2 h |

Each exceeds the frozen 3-hour budget before using its actual oracle-minimum
superstep count. They are therefore screened as host-time infeasible and are
not accelerator-performance rows. The generated JSON records each execution
ID, campaign/materialization hashes, graph hash, and both conservative rate
assumptions.

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
