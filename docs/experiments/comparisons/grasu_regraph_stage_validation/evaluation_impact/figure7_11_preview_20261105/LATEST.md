# Selected Evaluation Delivery

**Fig. 7 roadNet-CA (RN):** see the [nine-dataset preview](fig7_roadnet_ca_20261110/followup/fig7_nine_datasets.png)
and [November 10 supplement](fig7_roadnet_ca_20261110/README.md)
for all three paired FPGA results, frozen inputs and CPU checks. G+R is
33.31x faster on RN SSSP; Spine is 6.88x faster on RN CC and 1.33x faster
on RN ResPR. The supplement also tracks the other RN experiments.
It is separate from the frozen 24-row table and November 6 archive.

**Additional cycle-validation pilot:** see the [November 7 SSSP study](fpga_cycle_validation_20261107/README.md)
and [plot](fpga_cycle_validation_20261107/data/figures/fpga_cycle_validation.png).
All four predeclared small synthetic holdouts are within 20% (maximum
15.69%) for the matched device-event window. The separate zip includes
inputs, frozen development calibration, raw evidence and code. This is
not a replacement for the selected Figures 7--11 or their evidence limits.

Updated November 6, 2026. This is the selected **Figures 7--11 plus G/R
source-control delivery**, in the original handoff directory. The paper is
unchanged. This update incorporates the eight completed CC board pairs;
it does not claim a new rerun of every figure.

Download [the complete data/code/preview archive](evaluation_review_20261106.tar.gz).
The [file manifest](evaluation_review_20261106.manifest.json) records the
selection, checksums and all 24 Fig. 7 outcomes. Unlike the historical
`current_review.tar.gz`, this archive includes all eight CC measurements
and the LJ08 ResPR measurement. The old archive and `CURRENT.md` remain
frozen and are **not the selected delivery**.

The separate November 7
[affected-fraction FPGA supplement](affected_fraction_fpga_20261107/README.md)
is now colocated here, with its [figure preview](affected_fraction_fpga_20261107/handoff/figures/crossover.png),
data, raw logs and source zip. It contains 42 valid points and two retained
ResPR failures. It is not included in the frozen November 6 download and does
not replace or rerun Figures 7--11.

The November 7 [one-pass FPGA Fig. 8 attempt](current_fpga/fig8_persistent_once_20261107/README.md)
now adds [all eight attempted pairs](current_fpga/fig8_persistent_once_20261107/fig8_fpga.csv)
and a [preview](current_fpga/fig8_persistent_once_20261107/figures/fig8_fpga_update_throughput.png).
Four pairs pass: AU favors G by 1.12x; SU/WK/SO favor Spine by
1.20x/1.87x/13.00x. Spine fails PK and all three AU 131K batch-sweep cases;
there is **no valid complete FPGA Fig. 8b curve**. Raw logs, source archive,
clocks and failures are retained. These measurements use native Spine L2,
not the selected simulator L4 layout, and do not replace its data below.
The frozen November 6 download does not include this supplement.

## Data And Previews

All paths below are relative to this handoff directory. Downloading the
archive retrieves the selected CSVs, scopes, compact raw receipts, plotting
code, the supplied GraphyFlow reference zip, and all six PDF/PNG previews.
Large graph/state arrays, xclbins and toolchains are indexed by path/hash,
not duplicated in the archive.

| Item | Selected data | Preview | Coverage |
| --- | --- | --- | --- |
| G/R vs. public-source ports | [Stage CSV](current_fpga/gr_controls.csv), [scope](current_fpga/gr_scope.json) | [PNG](current_fpga/figures/gr_current_source_controls.png), [PDF](current_fpga/figures/gr_current_source_controls.pdf) | 3 G + 8 R hardware controls; one sample per arm |
| Fig. 7 | [Complete 24-row CSV](fig7_complete.csv) | [PNG](current_fpga/cc_direct_board_v1/figures/fig7_resident_checkpoint.png), [PDF](current_fpga/cc_direct_board_v1/figures/fig7_resident_checkpoint.pdf) | 8 datasets x SSSP/CC/ResPR; every pair measured and favors Spine |
| Fig. 8a | [Ten-batch CSV](fresh_simulator/portable_fig8_headroom_v1/fig8_ten_batch.csv) | [PNG](fresh_simulator/portable_fig8_headroom_v1/figures/fig8_update_prediction_headroom.png), [PDF](fresh_simulator/portable_fig8_headroom_v1/figures/fig8_update_prediction_headroom.pdf) | Same-host L4 follow-up, AU/SU/WK/SO/PK; measured CPU preparation plus predicted device/transfer/launch |
| Fig. 8b | [Fixed-total batch sweep](fresh_simulator/portable_fig8_headroom_v1/batch_sweep/fig8_batch_sensitivity.csv) | Same Fig. 8 preview | 131,072 updates in 10/100/1,000 batches on the same host |
| Fig. 9 | [Nine ratio rows](fresh_simulator/fig9_memory_energy_rows.csv), [18 absolute arms](fresh_simulator/fig9_arms.csv) | [PNG](fresh_simulator/figures/fig9_memory_hbm_prediction.png), [PDF](fresh_simulator/figures/fig9_memory_hbm_prediction.pdf) | AU/SU/WK x SSSP/CC/ResPR; simulated bytes and DRAMSim3 HBM energy |
| Fig. 10 | [Normalized stacks](fresh_simulator/fig10_normalized_breakdown_rows.csv), [absolute ten-stage rows](fresh_simulator/fig10_stage_rows.csv) | [PNG](fresh_simulator/figures/fig10_simulator_breakdown.png), [PDF](fresh_simulator/figures/fig10_simulator_breakdown.pdf) | 11 simulator stacks, including zero-net and PR correction; each stack totals 100% |
| Fig. 11 | [Prediction rows](fresh_simulator/fig11_e2e_prediction_rows.csv), [metrics](fresh_simulator/fig11_e2e_metric_rows.csv), [model](fresh_simulator/fig11_e2e_model.json) | [PNG](fresh_simulator/figures/fig11_realized_work_model.png), [PDF](fresh_simulator/figures/fig11_realized_work_model.pdf) | New fit from 42 executions, 41 model rows: 24 fit + 17 holdout |

## Interpretation

**G/R:** the current G stage is faster than its public-source PMA-only port
on all three controls; all eight adapter+R controls are within absolute
+/-15% of their public-source four-Little A4 ports (largest slowdown 13.54%).
These are matched stage-level FPGA controls, not reproduction of the
published GraSU/ReGraph throughput or original ReGraph 11+3 topology.
G and R have different stage boundaries; do not add the control points to
derive an end-to-end workload time.

**Fig. 7:** resident old converged graph/state, one update batch through
checked final state/readback; old-graph loading/convergence is outside.
Host preparation/waits/relaunch are included according to each row's
`boundary`. CC uses eight logical undirected insertions (16 physical records);
SSSP and ResPR use eight records. The ranges are SSSP 2.03x--24.01x,
CC 1.18x--26.61x, ResPR 1.51x--19.94x for Spine. The complete CSV is a
derived union, not a replacement for the frozen source CSVs. `source_csv`
locates each original row; source-specific columns remain present and
inapplicable fields are blank.

The SSSP/ResPR rows come from the frozen
[sixteen-pair checkpoint](current_fpga/resident_checkpoint_v3/README.md),
with its receipt hashes, clocks and explicit sample reuse. The CC rows come
from the [direct campaign](current_fpga/cc_direct_board_v1/README.md),
whose qualified status `MEASURED_WITHOUT_RAW_SKEW_REPORT` remains unchanged:
actual board timing and correctness passed, but the Spine raw routed
bus-skew report is missing. AU reuses a named same-image G+R sample.
Six CC batches leave labels unchanged; WK/R19 propagate for two rounds.
All eight ResPR batches have zero nonempty propagation at fixed FP32 epsilon
1e-6 and use an old-rank correction cache prepared outside the resident
timer, with its preparation cost recorded separately. They do not prove
nonempty ResPR propagation speedup. ResPR runs at 140/500/430 MHz after
the nominal route missed timing. Consult the source scopes before making
a claim about timing closure or identical host/device preparation.

**Figs. 8--11:** these are the selected fresh simulator/model results, not
new FPGA measurements or FPGA per-stage calibration. Fig. 8 explicitly uses
L4 initial placement, shared G metadata and future-union reservation, not
the routed four-copy layout. Its 1,000-batch point favors G+R by 1.715x;
do not describe all of Figs. 7--11 as all-win comparisons. Fig. 9's nine
main pairs favor Spine for bytes and modeled HBM subsystem energy; ResPR
has zero active propagation and timed correction replay. Fig. 10 is modeled
stage attribution. Syn = synthetic, FL = compact Flickr, L1/L3/L5 = carry
target levels 1/3/5. Fig. 11 predicts simulator cycles: overall holdout
R-squared 0.9803, median APE 10.0%, but real-input holdout median APE 58.1%
and max 89.1%. Those real-input errors must accompany any accuracy claim.

The [simulator guide](fresh_simulator/README.md) and [portable guide](PORTABLE.md)
explain boundaries and retained negative evidence, including the compact
Flickr ResPR propagation loss and legacy FullPR losses. FullPR is not a
current eight-dataset fourth series in this delivery.

## Verify And Redraw

Extract the archive into an empty directory and run from its root. Python
3.11+, Matplotlib, LaTeX `txfonts`, and `dvipng` are needed for plotting.
The manifest is at the extracted root; the full repository is not needed
to redraw the selected figures.

```sh
module=spine_cycle_sim.experiments.evaluation_impact.figure_refresh.evaluation_archive
python3 -m "$module" verify /path/to/evaluation_review_20261106.tar.gz
python3 -m "$module" render --output /tmp/evaluation-redrawn
```

All plots use the existing Python/Matplotlib GraphyFlow-style renderers,
TX Typewriter, and the common hatch settings. Edit `render.py` or
`render_current.py` in this directory for visual adjustments. To build a
new archive from a full checkout without rewriting the frozen selections:

```sh
module=spine_cycle_sim.experiments.evaluation_impact.figure_refresh.evaluation_archive
python3 -m "$module" build --resident resident_checkpoint_v3 --cc-direct \
  --output /tmp/evaluation-review-new.tar.gz
```

The build generates the complete Fig. 7 CSV inside the archive from the two
source tables and retains their individual measurement qualifications.
Redraw and packaging do not run a new experiment or edit the manuscript.
