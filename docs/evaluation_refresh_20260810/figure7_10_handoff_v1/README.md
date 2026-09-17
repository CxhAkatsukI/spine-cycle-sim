# Figures 7--11 Complete Handoff

This directory is the self-contained code, data, provenance, documentation,
and preview package for the revised evaluation Figures 7--11. It lives in the
simulator repository and does not modify the paper repository.

Figure 10 was corrected on 2026-09-17. Its former `7563b028...` inputs have
been replaced by the frozen v12 plugin `f1fca617...e324b70`, also used by the
Spine results in Figures 8, 9, and 11. The renderer now rejects a mismatch
between those figures, even when Figure 10 is internally consistent.
See [the correction and six-question audit](EVIDENCE_AUDIT_20260917.md).

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
- `evidence/fig10/`: losslessly compressed raw results, run summaries,
  architecture profiles, and the rejected CC zero-net attempt.
- `rebuild_fig10_data.py`: regenerate Figure 10 CSVs from that raw evidence
  using this repository's RQ3 analyzer; it does not refit Figure 11.
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

Here setup-inclusive means the host intervals actually recorded by each
runner. It is not a single timer around the entire application: some Spine
frontier preparation and result processing occur outside the measured
wrappers, and G+R preloads update buffers before its dynamic timer. The exact
boundary must be retained when reusing the figure; see audit item 1.

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

- `Zero-net / Syn`: reciprocal delete/reinsert on an eight-vertex SSSP
  fixture with unchanged final graph. The v12 implementation takes the
  full-rebuild fallback; this bar does not demonstrate no-repair behavior;
- `Shallow insert / AU, SU, WK`: batch-8 insertion traces;
- `Deep carry / L1, L3, L5`: forced carry through level 1, 3, or 5;
- `PR correction / FL, SU, WK`: thresholded Residual PageRank correction.
  FL is Flickr using the sink-free contract; SU/WK use the hardware warm
  dangling contract and converge during correction with zero propagation
  rounds. These contract choices are recorded per row in provenance;
- `Deletion fallback / Syn`: weighted-SSSP deletion fallback.

The ten-stage ledger is grouped as:

- `Maint.` = transfer + reduce + carry + directory;
- `Seed/pub.` = seed + switch/publication;
- `Resolve` = edge/history resolution;
- `App` = algorithm application;
- `Drain` = completion/control gaps outside the recorded component spans,
  source/reactivation drain, and synchronization.

Each bar is independently normalized to 100% of its own simulated end-to-end
device-cycle interval. It explains how the dominant stage changes with realized
work. It does not compare absolute latency between bars and is not an FPGA
per-stage measurement or FPGA-calibrated stage breakdown.

Reader/compute overlap is assigned once to the component whose interval ends
later, after maintenance/correction priority. The percentages are exclusive
critical-path attribution under this convention, not sums of independent
component busy times. Carry bars use the existing forced-carry fixture's
output/protocol checks; the dynamic graph cases use architecture and
mathematical oracle checks.

The eleven measured device windows are:

| Group | Labels | Cycles |
| --- | --- | --- |
| Zero-net | Syn | 28,343 |
| Shallow insert | AU / SU / WK | 58,332 / 58,866 / 40,004 |
| Deep carry | L1 / L3 / L5 | 11,331 / 14,750 / 22,997 |
| PR correction | FL / SU / WK | 920,110 / 11,491 / 13,040 |
| Deletion fallback | Syn | 41,484 |

For ZN, the untimed-for-this-figure cold prefix is 21,968 cycles; the raw
50,311-cycle execution minus that prefix gives the 28,343-cycle dynamic
window. The final graph is independently checked against the initial graph.
The unsuccessful CC zero-net run is retained under
`evidence/fig10/rejected_zero_net_cc/` and is excluded from the plotted rows.

SU/WK have explicit zero reader edges, compute edges, active vertices, owner
dispatches, and propagation rounds, with closed correction requests. The
previous analyzer treated their empty timestamps as missing evidence. The
corrected analyzer admits this verified empty path without changing simulated
cycles or the plugin. Their 137/135-cycle completion gaps are included in
Drain; they are not graph-computation cycles.

To regenerate the data and this figure in the simulator checkout:

```bash
python3 docs/evaluation_refresh_20260810/figure7_10_handoff_v1/rebuild_fig10_data.py
/data/tmp/chuxiao/spine-cycle-sim-eval-venv/bin/python \
  docs/evaluation_refresh_20260810/figure7_10_handoff_v1/render_all.py --only-fig10
```

The archived raw results are sufficient for this command; no FPGA run, plugin
rebuild, or access to the original `/data/tmp` campaigns is needed. Full
simulator rerun instructions for the new ZN example are in the audit document.

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

The September 17 Figure 10 correction does not refit or add ZN to this frozen
41-row model. Figure 11's archived stage-admission summary predates the
zero-round analysis fix (37 direct-stage rows); its observations, model,
predictions, split, and reported errors remain unchanged.

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
