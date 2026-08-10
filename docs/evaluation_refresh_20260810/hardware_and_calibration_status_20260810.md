# Hardware and Calibration Status

Date: 2026-08-10

This note records the current evidence boundary for the evaluation-refresh
packet. It is intentionally separate from the paper text.

## Figure 7 Timing Semantics

Panels (a)--(c) use routed U55C hardware for the full-graph sharded-K4
experiments. The timing window is:

1. The old graph is already converged and resident.
2. One update batch is applied.
3. The accelerator runs until the updated state converges.
4. The reported latency is setup-inclusive dynamic latency.

This is not a one-hop truncation.

Representative raw protocol checks:

- SSSP AU G+R: `executed_supersteps=2`, `hardware_converged=1`,
  `oracle_supersteps=2`.
- SSSP AU Delta.hls: `iterations=2`, `coverage=converged`.
- CC AU G+R: `executed_supersteps=1`, `hardware_converged=1`,
  `oracle_supersteps=1`.
- CC AU Delta.hls: `iterations=1`, `coverage=converged`.
- ResPR AU G+R: `pipeline_executions=1`, `propagation_rounds=0`,
  `hardware_converged=1`, `oracle_propagation_rounds=0`.
- ResPR AU Delta.hls: `iterations=0`, `coverage=converged`.

Panel (d) is different: it temporarily uses compact Full PageRank routed
hardware. The current compact FullPR protocol is fixed-round
(`rounds=3` / `coverage=three_iterations`), not convergence-to-epsilon. A
sharded-K4 FullPR route is running in the background and should replace this
panel if it passes.

## Existing Calibration Coverage

The repository contains older G+R K4 FPGA calibration evidence:

| Algorithm | Evidence directory | Holdout max abs error |
|---|---|---:|
| Weighted SSSP | `docs/evidence/k4_fpga_sssp_calibration_20260805` | 18.02% |
| CC | `docs/evidence/k4_fpga_cc_calibration_20260806` | 1.10% |
| Residual PR | `docs/evidence/k4_fpga_respr_component_calibration_20260806` | 5.69% |
| Full PR | `docs/evidence/k4_fpga_fullpr_component_calibration_20260806` | 2.59% |

These are useful sanity checks, but they are not yet the final calibration for
the full-graph sharded-K4 hardware matrix used by Figure 7.

## Figure 8--10 Status

Figures 8--10 in this directory are candidate formatting refreshes generated
from the archived simulator evidence:

- Figure 8: setup-inclusive update-only throughput CSVs.
- Figure 9: simulator memory/HBM-energy ledger from `formal_v7_primary`.
- Figure 10: RQ3 ten-stage latency ledger.

They should not be presented as final post-calibration figures until the
current sharded-K4 simulator is run against the same semantic contract as the
hardware matrix and the calibration/holdout gates are recorded.

## Active Calibration Refresh Run

A small calibration/refresh campaign is running from:

```bash
/data/tmp/chuxiao/evaluation_refresh_20260810_calibration_frozen/campaign_manifest.json
```

It covers AU/SU/WK, insert batch-8, three differential algorithms, and both
`spine` and `grasu_regraph_k4_shared`. It uses the frozen SST plugin directory:

```bash
/home/chuxiao/spine-cycle-sim-publication/build/sst
```

Monitor it with:

```bash
watch -n 5 python3 scripts/monitor_large_graph_campaign.py \
  --run-dir /data/tmp/chuxiao/evaluation_refresh_20260810_calibration_frozen/run \
  --max-rows 24
```

A first dry run with the current branch-local `build/sst` was rejected by the
contract's plugin-admission gate. That was expected after inspection: the
contract freezes plugin SHA
`7563b028e61e792e7043a582682dd26d0e3d8cc3e2407021f144519d0ef57bf6`, which
matches `/home/chuxiao/spine-cycle-sim-publication/build/sst/libspine_cycle.so`
and not the branch-local rebuild.

## Immediate Replacement Rule

- Figure 7(a)--(c): can be discussed as real FPGA evidence now.
- Figure 7(d): use as compact FullPR placeholder only.
- Figures 8--10: use for layout/review now; regenerate after calibration
  before treating them as final numerical evidence.
