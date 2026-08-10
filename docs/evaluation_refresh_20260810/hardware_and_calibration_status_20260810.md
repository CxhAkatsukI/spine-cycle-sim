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
(`rounds=3` / `coverage=three_iterations`), not convergence-to-epsilon. The
sharded-K4 FullPR route has now produced an xclbin and routed reports, but it
misses the 150 MHz target slightly (`WNS=-0.069 ns`, `TNS=-2.591 ns`, 84 setup
failing endpoints). It is therefore recorded as `PASS_TIMING_MISS` evidence and
should not replace panel (d) until its correctness/performance matrix is run
and its timing status is accepted for the intended claim.

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
from the current evidence packet where available:

- Figure 8: current setup-inclusive update-only throughput CSVs.
- Figure 9: current campaign memory/HBM-energy ledger; still partial until all
  AU/SU/WK pairs finish.
- Figure 10: current RQ3 ten-stage latency ledger.

Figure 8 and Figure 10 now pass the current-data alignment gate. Figure 9 is
still not final because the WikiTalk G+R CC and residual PageRank rows were
stopped by the campaign memory breaker and are being rerun.

Important Figure 8 boundary: Figure 8 uses setup-inclusive update-only
throughput, not simulator wall time and not full convergence time. The restored
path models persistent resident graph updates, host preprocessing, H2D
transfer, launch/sync cost, and device update cycles while explicitly disabling
graph computation. The current branch now contains the pieces needed for that
boundary:

- `spine_cycle_sim/experiments/persistent_update_only.py`
- `scripts/derive_update_only_manifest.py`
- `scripts/run_current_fig8_update_only_case.py`
- `scripts/export_persistent_update_setup_fig8.py`
- `cpp/tools/persistent_update_host_benchmark.cpp`

For the device portion, Spine uses the current SST maintenance-only path and
G+R uses the new `--update-only` weighted-PMA path, which stops after PMA update
maintenance and does not launch ReGraph compute. G+R update-only also uses a
lightweight host oracle that avoids SSSP Dijkstra because no graph-compute
correctness is claimed for this figure. Host preprocessing is measured by
`persistent_update_host_benchmark`.

The admitted current Fig. 8 evidence root is:

- `/data/tmp/chuxiao/evaluation_refresh_20260810_fig8_current_evidence`

The exported renderer input is:

- `/data/tmp/chuxiao/evaluation_refresh_20260810_fig8_current_csv`

The generated CSVs are marked `PASS_CURRENT_MODEL_DATA` and cover:

- cross dataset, 512 updates: AU, SU, WK, SO, PK;
- AU batch sweep: 64, 512, and 4096 updates.

The setup-inclusive speedups are:

- cross dataset: AU `10.98x`, SU `9.91x`, WK `18.18x`, SO `25.13x`, PK `6.49x`;
- AU batch sweep: 64 updates `11.61x`, 512 updates `11.38x`, 4096 updates
  `9.86x`.

Reproduction sketch:

```bash
python3 scripts/export_persistent_update_setup_fig8.py \
  --evidence-root /data/tmp/chuxiao/evaluation_refresh_20260810_fig8_current_evidence \
  --out-dir /data/tmp/chuxiao/evaluation_refresh_20260810_fig8_current_csv \
  --status PASS_CURRENT_MODEL_DATA \
  --cross-dataset au:AU \
  --cross-dataset su:SU \
  --cross-dataset wk:WK \
  --cross-dataset so:SO \
  --cross-dataset pk:PK \
  --batch-count 64 \
  --batch-count 512 \
  --batch-count 4096
```

Figure 10 current-data refresh: running `scripts/analyze_rq3_realized_work.py`
on the active calibration root plus current standalone RQ3 cases produced 15
latency rows and 21 regression rows, with all direct ten-stage ledgers closed.
The input roots are:

- `/data/tmp/chuxiao/evaluation_refresh_20260810_calibration_frozen`
- `/data/tmp/chuxiao/evaluation_refresh_20260810_rq3_current_carry`
- `/data/tmp/chuxiao/evaluation_refresh_20260810_rq3_current_targeted`
- `/data/tmp/chuxiao/evaluation_refresh_20260810_rq3_current_delete_shared`

The coverage summary is:

| RQ3 case class | Current probe status |
|---|---|
| zero-net | ready |
| shallow insertion | ready |
| deep carry | ready |
| PageRank correction | ready |
| deletion fallback | ready |

This is sufficient for the Figure 10 normalized breakdown panel. The broader
RQ3 linear cost-model fit is still under-sampled (`calibration_samples=6`,
`required_samples=9`) and should not be claimed as a final fitted E2E model
until more calibration rows are added.

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

Latest partial checkpoint: partial analysis reports `observed=15`, `pairs=6`,
`missing=3`. The completed pairs are:

- `sx_askubuntu / weighted_sssp / insert-8`: Spine `61,817` cycles versus
  G+R `179,053,544` cycles, or `2,896.5x` speedup.
- `sx_superuser / weighted_sssp / insert-8`: Spine `60,699` cycles versus
  G+R `291,909,003` cycles, or `4,809.1x` speedup.
- `sx_askubuntu / connected_components / insert-8`: Spine `2,183,292` cycles
  versus G+R `13,462,032` cycles, or `6.17x` speedup.
- `sx_superuser / connected_components / insert-8`: Spine `2,397,167` cycles
  versus G+R `21,367,179` cycles, or `8.91x` speedup.
- `sx_askubuntu / thresholded_residual_pagerank / insert-8`: Spine
  `2,175,289` cycles versus G+R `14,729,898` cycles, or `6.77x` speedup.
- `sx_superuser / thresholded_residual_pagerank / insert-8`: Spine
  `2,392,695` cycles versus G+R `23,162,486` cycles, or `9.68x` speedup.

The remaining jobs are the G+R side of wiki_talk_temporal SSSP, CC, and
residual PR. At the latest checkpoint wiki_talk_temporal SSSP was running and
the other two wiki_talk_temporal jobs were queued behind the campaign
scheduler's memory reserve.

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

Do not launch the sidecar while the machine is below the main recovery threshold.
If it is used, include the sidecar root in finalization:

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
