# Fresh Simulator Checkpoint

November 5, 2026. New runs and a new fit; no manuscript changes. This folder
is separate from the older figure CSVs in its parent. It is **not** a completed
FPGA-equivalent or all-win evaluation package. The parent index owns FPGA
Fig. 7 and source controls. Pending cases are not filled with older results.

## Data And Previews

| Figure | Data | Preview | Status |
| --- | --- | --- | --- |
| 8a | [Ten chronological batches](fig8_ten_batch.csv) | [PNG](figures/fig8_update_prediction.png), [PDF](figures/fig8_update_prediction.pdf) | AU/SU/WK complete; SO/PK pending memory admission |
| 8b | [Fixed 131,072-update sweep](fig8_batch_sensitivity.csv) | Same two-panel preview | 10/100/1,000 batches complete; G+R wins at 1,000 |
| 9 | [Nine ratios](fig9_memory_energy_rows.csv), [18 absolute arms](fig9_arms.csv) | [PNG](figures/fig9_memory_hbm_prediction.png), [PDF](figures/fig9_memory_hbm_prediction.pdf) | Complete declared AU/SU/WK x SSSP/CC/ResPR scope |
| 10 | [Normalized rows](fig10_normalized_breakdown_rows.csv), [absolute stages](fig10_stage_rows.csv) | [PNG](figures/fig10_simulator_breakdown.png), [PDF](figures/fig10_simulator_breakdown.pdf) | 11 correctness/ledger-admitted stacks, each normalized to 100% |
| 11 | [41 predictions](fig11_e2e_prediction_rows.csv), [metrics](fig11_e2e_metric_rows.csv), [model](fig11_e2e_model.json) | [PNG](figures/fig11_realized_work_model.png), [PDF](figures/fig11_realized_work_model.pdf) | 24 calibration + 17 unseen rows; ZN excluded from fit |

## Boundaries And Results

**Fig. 8:** one Release-host sample per arm, pinned GCC 15.2 and CPU affinity;
host setup/preparation plus simulated device time at 150 MHz, logical H2D at
12 GB/s, and 10 us launch per batch. Initial host preparation/upload is paid
once. Parsing, oracle computation, runtime allocation, XRT calls and final
readback are outside this prediction. The two arms retain PMA/Spine state
across batches; G does not rebuild/reset its device PMA per batch. G's wire
payload is 8 bytes, Spine's 16 bytes per update. This is update-only, **not
FPGA end-to-end timing**. Cross-dataset rows use 4,096 updates total in ten
batches. AU/SU/WK G+R/Spine ratios are 3.07/4.19/10.80. In the fixed-total
sweep they are 2.21/1.34/0.63: at 1,000 batches G+R is 1.59x faster, mainly
because of the predicted Spine device term, not host preparation. The b10
case explicitly overrides the frozen b100 input manifest's batch count;
graph and update bytes are unchanged. Scope and formula checks are in
[fig8_ten_batch_scope.json](fig8_ten_batch_scope.json).

**Fig. 9:** resident old state -> eight updates -> new convergence, device-only
traffic, 32 HBM channels and 32 outstanding requests/channel. The complete
direct-DRAMSim3 ledgers include all-channel background energy; this is HBM
model energy, not measured board power. All nine pairs favor Spine for bytes
and modeled HBM energy. Three ResPR pairs have no active propagation and
identical old/final rank hashes at fixed FP32 epsilon 1e-6 (not divided by V).
They do not establish a general nonempty-propagation advantage. ResPR uses
timed oracle-directed correction replay, not functional AXI seed execution.
G uses natural geometry/shared metadata, modeled full-directory drain, and
future-batch-union reservation; R uses prefetch/Gather reuse and a finite
Apply path. These profiles have **not** passed complete-image hardware
performance admission. The [scope file](fig9_scope.json) pins the full model,
inputs, source and absolute ledgers; do not label this as the exact routed
G+R image or infer hardware timing from the ratios.

**Fig. 10:** simulator stage attribution, **not FPGA stage calibration**.
Zero-net uses synthetic delete/reinsert with zero net change; shallow insert
uses AU/SU/WK; deep carry uses target levels L1/L3/L5; PR correction uses
compact Flickr (FL), SU and WK; deletion fallback is synthetic. Syn means
synthetic. Each bar divides its five grouped-stage sums by that execution's
complete ten-stage cycle total. Different input sizes are intentional; this
is a mechanism illustration, not a same-size speed comparison. Absolute
cycles, ten original stages and their grouping remain in the CSVs.

**Fig. 11:** predicts simulator cycles, not measured FPGA cycles. The 24 fit
rows alone determine the model; no holdout is used to fit. All 17 holdouts
give R-squared 0.9803 and median APE 10.0%, but the seven real-input holdouts
give median APE **58.1%** (maximum 89.1%). Do not present the first metric
alone as real-workload prediction accuracy. Per-stage R-squared is carry
0.9914, directory **0.1491**, seed 0.7454; the fitted directory slope is
negative. This does not establish a reliable causal directory cost model.
The larger full-model R-squared is dominated by scale differences. All 42
executions, including ZN, pass functional/ledger gates. An R19 CC case that
failed at a lower memory limit is preserved; its successful retry changes
the memory budget, not the profile/plugin/input or fit role.

## Receipts And Reproduction

- [Fig. 8 logs/configurations](fig8_ten_batch_receipts.tar.gz)
- [Fig. 9 per-channel ledgers, logs and configurations](fig9_receipts.tar.gz)
- [Fig. 10--11 run logs, profiles and manifests](fig10_11_receipts.tar.gz)
- [Fig. 10--11 scope and large-input hash index](fig10_11_scope.json)
- [Execution origin/retry map](measurement_origins.json)

Large graph/state arrays, binaries and toolchains are path/hash-indexed rather
than embedded. Replaying original runs requires those indexed external inputs;
redrawing the plots needs only this folder, the full repository's style package
and the Python renderer. The supplied GraphyFlow zip is SHA-checked; figures
use Matplotlib and LaTeX TX Typewriter, not pgfplots. Bar hatches use density 8,
black borders, a topmost x-axis, and no bottom categorical tick marks.

From the repository root (Python 3.11+, Matplotlib 3.11.2, txfonts/dvipng):

```sh
bundle=docs/experiments/comparisons/grasu_regraph_stage_validation/evaluation_impact/figure7_11_preview_20261105
python "$bundle/render.py" --fresh
python "$bundle/export_memory.py" --campaign /data/chuxiao/checks/source-retention-repair-20261104/fig9-fresh-v1 --output "$bundle/fresh_simulator"
python "$bundle/export_work.py" --campaign /data/chuxiao/checks/source-retention-repair-20261104/fig1011-fresh-v1 --replacement-campaign /data/chuxiao/checks/source-retention-repair-20261104/fig1011-r19cc-v3 --analysis /data/chuxiao/checks/source-retention-repair-20261104/fig1011-analysis-v1 --output "$bundle/fresh_simulator"
```

The exporters reparse raw receipts, check identities and conservation, replay
the energy sums or fit, and reject a changed claim/data boundary. Fig. 8's
exporter takes repeated `--case DATASET RESULTS_JSON` and optional
`--sweep BATCHES RESULTS_JSON`; the scope file lists exactly which are present.
Numerical runners live in `spine_cycle_sim.experiments.evaluation_impact.figure_refresh`:
`persistent_study` (8), `study` (9), `realized_work.run` (10--11). Their report
JSONs record full commands, compiler flags, affinity, source pins and memory
limits. Fresh exports do not mutate the November 3 frozen handoff.
