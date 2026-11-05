# Evaluation Review Archive

The manifest at the extracted archive root selects one explicit resident FPGA
checkpoint and contains the complete Fig. 7 outcome list. Read its
`complete` and `all_pairs_spine_wins` separately. Missing slots retain
their actual status, not a fabricated timing, timeout or speedup. This
archive is for review and redraw, not an FPGA rerun. Raw compact receipts
are included; large graphs, FPGA images and toolchains are indexed by hash.

| Plot | Selected data within this directory | Evidence boundary |
| --- | --- | --- |
| G/R control | [CSV](current_fpga/gr_controls.csv), [scope](current_fpga/gr_scope.json), [receipts](current_fpga/gr_receipts.tar.gz) | Single-sample same-workload FPGA public-source ports. G resident CU span is faster (one-sided gate); all eight adapter+R supersteps are within absolute +/-15%. Neither measures published throughput or whole convergence. |
| 7 | `current_fpga/<resident_checkpoint>/fig7_resident_checkpoint.csv`, scope and receipts beside it | Same old converged state, eight updates, new state checked against the oracle. Resident wall time includes waits, relaunch and final readback; preloaded old state is outside. |
| 8 | [Ten batches](fresh_simulator/portable_fig8_headroom_v1/fig8_ten_batch.csv), [fixed-total sweep](fresh_simulator/portable_fig8_headroom_v1/batch_sweep/fig8_batch_sensitivity.csv) | Same-host measured CPU prep + modeled device/transfer/launch. Shared G metadata with future-union reservation and L4 initialization, not exact routed G. The 1,000-batch point favors G+R by 1.715x. |
| 9 | [Ratios](fresh_simulator/fig9_memory_energy_rows.csv), [absolute arms](fresh_simulator/fig9_arms.csv), [scope](fresh_simulator/fig9_scope.json) | Simulator bytes and DRAMSim3 modeled HBM subsystem energy, not board power. ResPR has zero active propagation. No exact routed-image traffic parity claim. |
| 10 | [Stacks](fresh_simulator/fig10_normalized_breakdown_rows.csv), [absolute stages](fresh_simulator/fig10_stage_rows.csv) | Eleven normalized simulator stacks from closed ten-stage ledgers. Syn is synthetic, FL is compact Flickr, and L1/L3/L5 are carry target levels. No FPGA stage calibration. |
| 11 | [Predictions](fresh_simulator/fig11_e2e_prediction_rows.csv), [metrics](fresh_simulator/fig11_e2e_metric_rows.csv) | Simulator cycles, not FPGA: 24 fit / 17 holdout, excluding zero-net from fitting. Overall holdout median APE 10.0%; real-input subset median 58.1%, max 89.1%. |

The CC batch has eight logical undirected insertions, stored as sixteen
directed records on each arm. The SSSP and ResPR batches have eight records.
CC receipts use the host-pack-to-final-readback boundary for the resident
old graph; SSSP and ResPR retain their resident-update-to-readback labels.
Fig. 7 does not charge the initial G+R frontier packing inside its timer;
Spine source-list construction is inside. The selected ResPR correction
cache is built from old graph/rank outside the timer, with its cost reported
separately. It is not device correction. The measured ResPR pairs in these
checkpoints have zero nonempty propagation rounds at fixed FP32 epsilon 1e-6. They do
not establish propagation speedup. The ResPR arms both use 140/500/430-MHz
clocks after nominal timing failed; measured board success is not nominal
timing closure. Consult row-level clock, sample-reuse and receipt fields.

These selections do not replace the negative evidence: the older CC AU
case lost by 3.18x with seven other old cases exceeding the layout limit;
the older ResPR PK host lost before its qualified retime; compact Flickr
ResPR with real propagation still loses (35.08 vs. 4.76 ms). The legacy
compact FullPR cases lost by 22x--49x and are not current eight-graph data.
The Fig. 8 sweep loss and Fig. 11 real-input errors remain in this archive.

## Verify And Redraw

From a checkout containing the explicit checkpoint:

```sh
module=spine_cycle_sim.experiments.evaluation_impact.figure_refresh.evaluation_archive
python3 -m "$module" build --resident resident_checkpoint_v3 --output /tmp/eval-review.tar.gz
python3 -m "$module" verify /tmp/eval-review.tar.gz
```

Change `--resident` only to a reviewed checkpoint from the same replayed
exporter. The verifier checks the 24 slots, timings and ratios, the exact
control CSV pin, and the per-file archive hashes. The exporter, not the
plotter, is responsible for admitting board runs against raw receipts.

Extract the archive into an empty directory, then run from the extracted
root with Python 3.11+, Matplotlib, LaTeX `txfonts`, and `dvipng`:

```sh
module=spine_cycle_sim.experiments.evaluation_impact.figure_refresh.evaluation_archive
python3 -m "$module" render --output /tmp/eval-review-rebuilt
```

The output directory and archive path must not already exist. The redraw
reuses the existing Python/Matplotlib GraphyFlow-style renderers, including
TX Typewriter and the original style archive. No experiment is rerun and
no manuscript files are edited.
