# Current Review Selection

Frozen November 5 checkpoint. **Not a completed evaluation: 15/24 FPGA
pairs are available.** All eight CC pairs and LJ08 ResPR are absent. A dash
means unmeasured, not a timeout, projection, zero speedup or a losing sample.
The paper is unchanged. Earlier dated exports remain untouched.

Use this page instead of choosing among the historical previews in the
parent README. The [self-contained plotting/data archive](current_review.tar.gz)
and [per-file hash manifest](current_review_manifest.json) select exactly
the following inputs and Python renderers. No experiment is rerun by rendering.
Large graphs, state arrays, FPGA images and toolchains are external,
hash-indexed dependencies in the archived receipts.

## Selected Figures

| Plot | Preview | Data and evidence | Meaning |
| --- | --- | --- | --- |
| G/R public-source controls | [PNG](current_fpga/figures/gr_current_source_controls.png), [PDF](current_fpga/figures/gr_current_source_controls.pdf) | [11 controls](current_fpga/gr_controls.csv), [scope](current_fpga/gr_scope.json), [receipts](current_fpga/gr_receipts.tar.gz) | FPGA, one sample per arm. G is faster; all eight R points lie within absolute +/-15% |
| 7 | [PNG](current_fpga/resident_checkpoint_v2/figures/fig7_resident_checkpoint.png), [PDF](current_fpga/resident_checkpoint_v2/figures/fig7_resident_checkpoint.pdf) | [24 measured/missing slots](current_fpga/resident_checkpoint_v2/fig7_resident_checkpoint.csv), [scope](current_fpga/resident_checkpoint_v2/scope.json), [receipts](current_fpga/resident_checkpoint_v2/receipts.tar.gz) | FPGA: eight SSSP and seven ResPR pairs measured; nine missing |
| 8 | [PNG](fresh_simulator/portable_fig8_headroom_v1/figures/fig8_update_prediction_headroom.png), [PDF](fresh_simulator/portable_fig8_headroom_v1/figures/fig8_update_prediction_headroom.pdf) | [Ten batches](fresh_simulator/portable_fig8_headroom_v1/fig8_ten_batch.csv), [fixed-total sweep](fresh_simulator/portable_fig8_headroom_v1/batch_sweep/fig8_batch_sensitivity.csv), [scope](fresh_simulator/portable_fig8_headroom_v1/scope.json), [sweep scope](fresh_simulator/portable_fig8_headroom_v1/batch_sweep/scope.json) | Same-host L4 CPU + simulator prediction; both panels complete |
| 9 | [PNG](fresh_simulator/figures/fig9_memory_hbm_prediction.png), [PDF](fresh_simulator/figures/fig9_memory_hbm_prediction.pdf) | [Nine ratios](fresh_simulator/fig9_memory_energy_rows.csv), [18 absolute arms](fresh_simulator/fig9_arms.csv), [scope](fresh_simulator/fig9_scope.json), [receipts](fresh_simulator/fig9_receipts.tar.gz) | Simulated accepted bytes and DRAMSim3 HBM energy, not board power |
| 10 | [PNG](fresh_simulator/figures/fig10_simulator_breakdown.png), [PDF](fresh_simulator/figures/fig10_simulator_breakdown.pdf) | [11 normalized stacks](fresh_simulator/fig10_normalized_breakdown_rows.csv), [absolute stages](fresh_simulator/fig10_stage_rows.csv), [scope](fresh_simulator/fig10_11_scope.json) | Simulator stage attribution; every stack is normalized to 100% |
| 11 | [PNG](fresh_simulator/figures/fig11_realized_work_model.png), [PDF](fresh_simulator/figures/fig11_realized_work_model.pdf) | [41 predictions](fresh_simulator/fig11_e2e_prediction_rows.csv), [metrics](fresh_simulator/fig11_e2e_metric_rows.csv), [new model](fresh_simulator/fig11_e2e_model.json), [receipts](fresh_simulator/fig10_11_receipts.tar.gz) | Fit to simulator output: 24 calibration + 17 unseen rows; not FPGA prediction accuracy |

## Boundaries

**Controls:** G measures resident update-CU event span, not upload or full
host setup. R measures adapter + integrated R against the public four-Little
ReGraph port on the same input/superstep, not complete convergence or the
publication's original topology. Worst current R slowdown is 13.54% (SSSP
AU); current G is 0.382x/0.401x/0.572x its public control for SSSP/CC/ResPR.
Faster G points satisfy an at-most-15%-slower gate, not absolute +/-15%
parity. These results do not reproduce the papers' published throughput.

**Fig. 7:** old graph/converged state, eight updates, new-state convergence,
resident wall time including host waits/relaunch and final readback; old-state
setup excluded. The initial G+R frontier packing is outside its timer;
Spine source-list construction is inside. All 15 measured pairs favor Spine:
SSSP 2.03x--24.01x, ResPR 1.51x--19.29x. Every measured ResPR row has zero
nonempty propagation rounds at fixed FP32 epsilon 1e-6 (not epsilon/V).
The qualified Spine correction cache is built from old graph/rank outside
the resident timer and its preparation cost is reported separately. It is
not a device correction engine; do not claim propagation speedup from these
rows. SSSP uses 150/500/450-MHz data/kernel/HBM clocks. Both ResPR arms use
140/500/430 MHz after nominal timing failed; board success is not new timing
closure. The exact G+R images passed the controls above.

**Fig. 8:** measured Release CPU preparation + simulated device cycles/150 MHz
+ logical H2D bytes/12 GB/s + 10 us launch per batch. Parsing, oracle work,
runtime allocation, XRT and final readback are excluded. This is update-only,
not result convergence. Both panels use Xeon 8375C, CPU 20, GCC 15.2 and
explicit L4 initial placement, with state retained across chronological
batches. Panel a has 4,096 total updates in ten batches on AU/SU/WK/SO/PK.
Panel b fixes 131,072 total updates and varies 10/100/1,000 batches; G+R/Spine
ratios are 1.822/1.116/**0.583**. The final point is a **G+R 1.715x win**.
Initial preparation/upload is charged once. G uses shared metadata and
future-batch-union reservation, not the exact four-copy routed G layout;
L4 bootstrap parity with HLS is not established. The former L2 PK capacity
failure remains in the repository; it was not rewritten as a pass.

**Fig. 9:** AU/SU/WK x SSSP/CC/ResPR, old-state residency through eight updates
and convergence; device request ledgers with all-channel background energy
included. Both arms use 32 channels and 32 outstanding requests per channel.
All nine pairs favor Spine for bytes and modeled HBM energy. ResPR has zero
active propagation and timed oracle-directed correction replay, not functional
AXI seed execution. G uses natural/shared metadata and future-union reservation;
R models prefetch/Gather reuse and finite Apply. These profiles have not
passed complete-image FPGA performance admission. They must not be labeled
traffic/energy measurements of the exact routed G+R image.

**Figs. 10--11:** frozen plugin
`1a417c2f78c48911dfe9b84bd76759ad7dc634036bbad1b1a4684d783190fe62`,
dense default Apply. All 42 executions pass correctness and closed-ledger
checks. Fig. 10 groups ten stages into maintenance, seed/publication, resolve,
application, and drain/sync; Syn = synthetic, FL = compact Flickr, AU/SU/WK
are dataset abbreviations, and L1/L3/L5 are carry target levels. The stacks
include zero-net and PR correction. No FPGA per-stage calibration is claimed.
Fig. 11 excludes zero-net from fitting, uses only 24 calibration rows to fit,
and retains 17 holdouts. Holdout R-squared is 0.9803, median APE 10.0%; the
seven real-input holdouts instead have median APE **58.1%**, maximum 89.1%.
Scale differences dominate R-squared. Per-stage carry/directory/seed
R-squared is 0.9914/**0.1491**/0.7454; the negative directory fit slope is not
a reliable causal cost model. Keep the real-input error beside the overall
metric. [Execution origins](fresh_simulator/measurement_origins.json) retain
the lower-memory R19 CC failure and unchanged-numerics successful retry.

## Missing And Negative Evidence

- CC's replacement image is being compiled under explicit containment; no
  replacement timing exists at this checkpoint. The old full-AU comparison
  lost to G+R by 3.18x; seven other old CC cases overflowed the old row limit.
- LJ08 ResPR stopped under memory-pressure supervision before a paired result.
  Zero cgroup OOM events do not make that abort a successful measurement.
- The original PK ResPR host lost before its qualified cache retime. A compact
  Flickr case with twelve propagation rounds still loses: Spine 35.08 ms vs.
  G+R 4.76 ms. Legacy compact FullPR loses by 22x--49x. None is a current
  eight-graph FullPR result.
- Fig. 8's 1,000-batch loss and Fig. 11's real-input errors remain visible.
  Consequently neither this bundle nor the 15 Fig. 7 wins proves an all-win
  evaluation or a completed architecture/latency calibration.

The [full dated index on GitHub](https://github.com/CxhAkatsukI/spine-cycle-sim/blob/codex/r-tail-retention-screen/docs/experiments/comparisons/grasu_regraph_stage_validation/evaluation_impact/figure7_11_preview_20261105/README.md)
preserves failed attempts and earlier scopes. The review archive includes
small selected receipts, not every historical experiment.

## Redraw And Verify

Extract the archive in an empty directory. Keep its repository-relative
layout. Requires Python 3.11+, Matplotlib (tested 3.11.2), LaTeX `txfonts`,
and `dvipng`. All plots use Matplotlib with TX Typewriter, density-8 hatches,
black bar borders and topmost axes, based on the supplied SHA-checked
`GraphyFlow_Plot.zip`. No pgfplots rendering or paper editing is involved.

Run from the extracted root or full repository root:

```sh
pkg=docs/experiments/comparisons/grasu_regraph_stage_validation/evaluation_impact/figure7_11_preview_20261105
python3 "$pkg/render_review.py" --output /tmp/review-check --verify-only
python3 "$pkg/render_review.py" --output /tmp/review-rebuilt
```

The output directory must not already exist, so previews cannot accidentally
overwrite frozen evidence. The renderer verifies every selected file before
drawing and explicitly chooses same-host L4 Fig. 8, never the older partial
local cohort. The archive also contains the original style renderer and zip,
so it does not depend on another checkout or the original `/data` paths.
Manifest hashes pin the added plotting code; the recorded base commit is not
misrepresented as containing files introduced afterward.
