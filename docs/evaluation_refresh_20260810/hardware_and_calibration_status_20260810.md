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

Important Figure 8 boundary: the archived Figure 8 evidence came from a
dedicated `pure_update_only` runner that modeled persistent resident graph
updates, host preprocessing, H2D transfer, launch/sync cost, and device update
cycles while explicitly disabling graph computation. That runner is not present
in the current sharded-K4 branch. The current formal publication rows contain
device execution cycles and simulator CPU wall time, but the `host_wall_seconds`
field is the wall-clock time spent running the simulator, not modeled host
preprocessing time for the architecture. Therefore Figure 8 cannot be refreshed
by simply reusing formal campaign `pair_rows.csv`.

The closest current-style update-only evidence found so far is
`/data/tmp/chuxiao/large_graph_campaign_v1/formal_v8_au_update_scaling`, which
contains AU update-only device-cycle rows for batch sizes 64, 1024, 16384, and
131072. It is useful for sanity checking the device update path, but it is not
the same as the archived setup-inclusive Figure 8 metric. A final current-model
Figure 8 replacement needs one of the following:

1. restore/rebuild the persistent update-only runner against the current
   sharded-K4 SST element and regenerate both cross-dataset and batch-size
   setup-inclusive rows; or
2. explicitly redefine Figure 8 as device-only update throughput and rewrite the
   figure caption/evidence boundary accordingly.

Until one of these is done, Figure 8 remains a layout candidate, not final
numeric evidence.

Implementation checkpoint: the setup-inclusive update-only accounting module
and Fig. 8 CSV exporter have been restored in the current branch:

- `spine_cycle_sim/experiments/persistent_update_only.py`
- `scripts/export_persistent_update_setup_fig8.py`

The renderer now requires a `persistent_update_setup_manifest.json` with
`status=PASS_CURRENT_MODEL_DATA` before accepting `--fig8-data-dir` as current
evidence. The remaining Fig. 8 blocker is the current sharded-K4 device/host
runner that produces admitted `pure_update_only` Spine and G+R evidence.

Figure 10 current-data probe: running `scripts/analyze_rq3_realized_work.py`
on `/data/tmp/chuxiao/evaluation_refresh_20260810_calibration_frozen` produced
9 latency rows and 21 regression rows, with all direct ten-stage ledgers closed.
However, the coverage summary is:

| RQ3 case class | Current probe status |
|---|---|
| zero-net | missing |
| shallow insertion | ready |
| deep carry | missing |
| PageRank correction | missing/partial for the fixed Figure 10 IDs |
| deletion fallback | missing |

The current Fig. 7/Fig. 9 calibration campaign is therefore not sufficient to
fully replace Figure 10. A final current-model Figure 10 needs a dedicated RQ3
trace campaign that regenerates the zero-net, forced-carry, PageRank-correction,
and deletion-fallback rows under the frozen sharded-K4 plugin.

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

Latest partial checkpoint, `2026-08-10 21:10:56 CST`: partial analysis reports
`observed=10`, `pairs=1`, `missing=8`. The completed pair is
`sx_askubuntu / weighted_sssp / insert-8`: Spine `61,817` cycles versus
G+R `179,053,544` cycles, or `2,896.5x` speedup for this calibration row.

Monitor it with:

```bash
watch -n 5 python3 scripts/monitor_large_graph_campaign.py \
  --run-dir /data/tmp/chuxiao/evaluation_refresh_20260810_calibration_frozen/run \
  --max-rows 24
```

Estimate the remaining cycle budget with:

```bash
/data/tmp/chuxiao/spine-cycle-sim-eval-venv/bin/python \
  scripts/estimate_evaluation_campaign_eta.py
```

If the main runner leaves G+R long-tail jobs queued and memory has recovered
well above the campaign recovery threshold, a sidecar campaign may be launched
from:

```bash
/data/tmp/chuxiao/evaluation_refresh_20260810_calibration_sidecar_queued/campaign_manifest.json
```

Use:

```bash
/data/tmp/chuxiao/spine-cycle-sim-eval-venv/bin/python \
  scripts/run_large_graph_campaign.py \
  --manifest /data/tmp/chuxiao/evaluation_refresh_20260810_calibration_sidecar_queued/campaign_manifest.json \
  --run-dir /data/tmp/chuxiao/evaluation_refresh_20260810_calibration_sidecar_queued/run \
  --jobs 3 \
  --large-jobs 2 \
  --memory-reserve-gib 72 \
  --memory-emergency-gib 64 \
  --memory-recovery-gib 96 \
  --sample-seconds 10 \
  --no-progress-warn-minutes 20
```

Do not launch the sidecar while the machine is below the main recovery threshold
or while the FullPR route is consuming placement memory. If it is used, include
the sidecar root in finalization:

```bash
/data/tmp/chuxiao/spine-cycle-sim-eval-venv/bin/python \
  scripts/finalize_evaluation_refresh.py \
  --extra-result-root /data/tmp/chuxiao/evaluation_refresh_20260810_calibration_sidecar_queued
```

Analyze partial or complete results with:

```bash
python3 scripts/analyze_publication_experiment_campaign.py \
  --result-root /data/tmp/chuxiao/evaluation_refresh_20260810_calibration_frozen \
  --manifest /data/tmp/chuxiao/evaluation_refresh_20260810_calibration_frozen/campaign_manifest.json \
  --result-transition-contract configs/contracts/large_graph_publication_campaign_fullgraph_v8.json \
  --required-system spine \
  --required-system grasu_regraph_k4_shared \
  --out-dir /data/tmp/chuxiao/evaluation_refresh_20260810_calibration_frozen/analysis_partial
```

Do not pass the nested `runs/` directory as `--result-root`; the analysis
loader expects `runs/*/case_result.json` under the supplied root.

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
