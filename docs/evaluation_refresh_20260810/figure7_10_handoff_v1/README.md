# Figures 7--11 Complete Handoff

This directory is the self-contained code, data, provenance, documentation,
and preview package for the revised evaluation Figures 7--11. It lives in the
simulator repository and does not modify the paper repository.

## One-command reproduction

Prerequisites are Python 3, the package in `requirements.txt`, and a LaTeX
installation containing `txfonts` (TX Typewriter).

```bash
cd /home/chuxiao/spine-cycle-sim-sharded-k4-v3/docs/evaluation_refresh_20260810/figure7_10_handoff_v1
/data/tmp/chuxiao/spine-cycle-sim-eval-venv/bin/python render_all.py
```

The renderer reads only `data/` and `provenance/` within this directory. It
validates evidence status, frozen hashes, workload coverage, simulator identity,
Figure 10 cycle conservation, and Figure 11 split/model hashes before drawing.

## Package layout

- `render_all.py`: complete standalone Python renderer for all five figures.
- `data/`: frozen CSV inputs used by the renderer.
- `provenance/`: source manifests and evidence boundaries for each figure.
- `figures/`: PDF, PNG, and combined-preview outputs.
- `reference/GraphyFlow_Plot.zip`: the supplied visual-style reference,
  preserved verbatim with SHA-256
  `a1b053bbd7c20cd9ce5c79d44a11027327da1c72a402487f5c8c659b71c18a27`.
- `manifest.json`: hashes of all package inputs and generated outputs.

All figures are generated with Python/Matplotlib. The code follows the supplied
GraphyFlow conventions for grouped bars, hatch encoding, explicit borders,
compact legends, inward ticks, vector PDF output, and raster previews. Text is
rendered using TX Typewriter (`txtt`).

## Figure 7: End-to-end dynamic-update latency

**Data:** `data/fig7_fpga_speedup.csv`

Panel (a) groups results by complete graph: AU, SU, WK, SO, PK, LJ, LJ08, and
R19. Each dataset group contains adjacent Residual PageRank, CC, and weighted
SSSP bars comparing Delta.hls against destination-sharded K4 G+R. Each bar is
the median of three correctness-admitted routed-U55C repetitions; its error bar
is the observed minimum/maximum range. The timing window starts from an old
graph that is already resident and converged, applies one batch, and ends when
the updated state converges. It includes setup/orchestration in the measured
dynamic latency window.

Panel (b) is deliberately narrower: three compact, one-partition Full PageRank
FPGA workloads (AM, WG, FL), each run for the same fixed three-round contract.
It demonstrates the current FullPR disadvantage but is not complete-graph
evidence. No projected or timeout-bounded value enters Figure 7.

The y-axis is speedup `G+R / Delta.hls`; values above one favor Delta.hls and
values below one favor G+R.

## Figure 8: Persistent update-only throughput

**Data:**

- `data/fig8_update_cross_dataset.csv`
- `data/fig8_update_batch_sensitivity.csv`

Panel (a) compares 512-update batches on AU, SU, WK, SO, and PK. Panel (b)
sweeps 64, 512, and 4,096 updates per batch on AU. The metric includes measured
host preprocessing, modeled PCIe transfer and launch/synchronization overhead,
and frozen persistent device-update cycles. It excludes graph propagation and
convergence by construction.

The y-axis is update-throughput speedup `Delta.hls / G+R`. These results must
not be described as end-to-end graph-algorithm throughput.

## Figure 9: Memory traffic and HBM energy

**Data:** `data/fig9_memory_energy_rows.csv`

Both panels contain nine correctness- and ledger-admitted simulator pairs:
SSSP, CC, and thresholded Residual PageRank on AU, SU, and WK. The three dataset
bars are adjacent within each algorithm group and encoded by one shared legend.

- Panel (a): accepted backend-byte ratio `G+R / Delta.hls`.
- Panel (b): bound-channel DRAMSim3 energy ratio `G+R / Delta.hls`.

All rows close request, arbitration, completion, and byte ledgers under the
shared memory model. The energy panel is an HBM-subsystem estimate, not total
accelerator power, FPGA board power, or ASIC core energy.

## Figure 10: Simulator-predicted realized-work breakdown

**Data:** `data/fig10_normalized_breakdown_rows.csv`

The eleven bars cover all five requested workload classes:

- `Zero-net / Syn`: target no-repair zero-net path;
- `Shallow insert / AU, SU, WK`: batch-8 insertion traces;
- `Deep carry / L1, L3, L5`: forced carry through level 1, 3, or 5;
- `PR correction / FL, SU, WK`: thresholded Residual PageRank correction;
- `Deletion fallback / Syn`: weighted-SSSP deletion fallback.

The ten-stage ledger is grouped as:

- `Maint.` = transfer + reduce + carry + directory;
- `Seed/pub.` = seed + switch/publication;
- `Resolve` = edge/history resolution;
- `App` = algorithm application;
- `Drain` = source/reactivation drain + synchronization.

Each bar is independently normalized to 100% of its own simulated end-to-end
device-cycle interval. It explains how the dominant stage changes with realized
work. It does not compare absolute latency between bars and is not an FPGA
per-stage measurement or FPGA-calibrated stage breakdown.

## Figure 11: Realized-work model prediction versus simulator cycles

**Data:**

- `data/fig11_rq3_prediction_rows.csv`
- `data/fig11_rq3_metric_rows.csv`
- `data/fig11_rq3_model.json`
- `data/fig11_rq3_summary.json`

The x-axis is the execution-driven simulator's observed end-to-end cycle
count. The y-axis is the nonnegative realized-work model prediction. Square
markers are the 24 calibration rows; circular markers are the 17 trace
holdout rows. Calibration rows are used to fit the model, while holdout rows
are never used for fitting. The line is the identity line, not a regression
line.

The frozen input combines the existing 21 current-v12 cases with 20 new
correctness-admitted carry cases. The new cases use batch sizes of 1, 4, 16,
and 32 edges and forced carry levels L1--L5. All 41 rows use the same frozen
simulator plugin (`f1fca617...e324b70`). The expanded model has 24 calibration
rows, 17 trace holdout rows, and 7 real-trace holdout rows.

The expanded trace holdout has `R^2 = 0.981` and median absolute percentage
error `9.8%`. The real-trace holdout has `R^2 = 0.978` but median absolute
percentage error `57.3%` (maximum `90.2%`). Therefore this figure is admitted
as a **diagnostic simulator-model figure**: it supports realized-work trend
and bottleneck attribution, but it is not an FPGA-accurate absolute latency
claim. In particular, the high real-trace holdout error must remain visible
and must not be hidden by reporting only the calibration fit or the combined
`R^2`.

The model still has no zero-net row in this expanded input. That missing
coverage is recorded in `data/fig11_rq3_summary.json`; it is not silently
filled with a projected value.

## Evidence summary

| Figure | Primary evidence | Scope |
|---|---|---|
| 7 | Routed U55C measurements | Dynamic update through convergence; compact fixed-round FullPR exception |
| 8 | Measured host setup + frozen persistent update models | Update-only, no propagation |
| 9 | Execution-driven simulator memory ledger + DRAMSim3 | Relative accepted bytes and HBM energy |
| 10 | Execution-driven cycle simulator timestamps | Normalized stage attribution |
| 11 | Execution-driven simulator cycles + realized-work model | Diagnostic model fit and holdout error; not hardware calibration |

The provenance JSON files retain the raw evidence paths and hashes used to
freeze each CSV. Those external paths are not needed to redraw the figures;
they are retained for scientific traceability.
