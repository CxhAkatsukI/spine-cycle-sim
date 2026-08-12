# Figures 7--10 Complete Handoff

This directory is the self-contained code, data, provenance, documentation,
and preview package for the revised evaluation Figures 7--10. It lives in the
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
and Figure 10 cycle conservation before drawing any figure.

## Package layout

- `render_all.py`: complete standalone Python renderer for all four figures.
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

Panels (a)--(c) compare Delta.hls against destination-sharded K4 G+R on eight
complete graphs: AU, SU, WK, SO, PK, LJ, LJ08, and R19. Each point is the median
of three correctness-admitted routed-U55C repetitions; the error bar is the
observed minimum/maximum range. The timing window starts from an old graph that
is already resident and converged, applies one batch, and ends when the updated
state converges. It includes setup/orchestration in the measured dynamic
latency window.

Panel (d) is deliberately narrower: three compact, one-partition Full PageRank
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

## Evidence summary

| Figure | Primary evidence | Scope |
|---|---|---|
| 7 | Routed U55C measurements | Dynamic update through convergence; compact fixed-round FullPR exception |
| 8 | Measured host setup + frozen persistent update models | Update-only, no propagation |
| 9 | Execution-driven simulator memory ledger + DRAMSim3 | Relative accepted bytes and HBM energy |
| 10 | Execution-driven cycle simulator timestamps | Normalized stage attribution |

The provenance JSON files retain the raw evidence paths and hashes used to
freeze each CSV. Those external paths are not needed to redraw the figures;
they are retained for scientific traceability.
