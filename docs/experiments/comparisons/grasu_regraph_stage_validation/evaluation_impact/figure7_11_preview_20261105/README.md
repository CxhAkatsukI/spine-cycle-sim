# G/R Source Controls and Evaluation Plots

The latest incremental FPGA export is the [sixteen-pair checkpoint](current_fpga/resident_checkpoint_v3/README.md):
all eight SSSP and eight ResPR pairs are measured; eight CC pairs remain
missing. The [portable review entry](CURRENT.md) still selects its frozen
fifteen-pair archive, the complete same-host L4 Fig. 8 follow-up and the
negative results. It has not silently incorporated this increment. Older
preview commands below deliberately retain their earlier selections.

## November 5 Fresh Checkpoint

Start with the [current FPGA G/R controls](current_fpga/README.md) and
[current resident FPGA checkpoint](current_fpga/resident_checkpoint_v3/README.md).
The former contains eleven replayed controls on the exact current baseline
images: all eight R points are within absolute +/-15%, and all three G points
are faster than their public-source ports. The latter has **16 of 24** measured
Fig. 7 pairs: all eight SSSP and eight ResPR cases favor Spine. Eight CC cases
remain missing, not zero-speedup measurements. The grouped preview
uses one algorithm series per dataset, as requested.

Later resident exports may repeat `--retimes` with the full original
eight-status matrix first and explicit remainder matrices after it. All raw
matrices are archived unchanged, with a per-dataset source map. A later
pending/failed status cannot erase an accepted sample; conflicting measured
samples are rejected instead of choosing the faster one. Each later export
gets a new directory, leaving the thirteen-pair checkpoint frozen.

The [fresh simulator data and previews](fresh_simulator/README.md) come from new
executions and replayed analysis, not the older CSV files listed below. Fig. 8
contains a local AU/SU/WK ten-batch cohort and all three fixed-total batch
counts. A [separate same-host remote cohort](fresh_simulator/portable_fig8/README.md)
completes AU/SU/WK/SO, with PK's capacity failure retained; the local SO/PK
jobs remain queued. Fig. 9 has nine fresh pairs; Figs.
10--11 have 42 fresh executions, with 41 fit/holdout rows. Hardware source
retention is a separate claim, not implied by these predictions.

The [remote CPU protocol](REMOTE_CPU.md) documents the isolated portable
runner and its unchanged numerical settings. Remote and local host timings
belong to separate cohorts; a queued or running remote job is not an accepted
replacement point.

The protocol also records the [separate L4 bootstrap-headroom follow-up](fresh_simulator/portable_fig8_headroom_v1/README.md):
all five remote ten-batch cases and a matching same-host
131,072-update batch sweep now complete. The sweep ratios are
1.822/1.116/0.583: G+R wins at 1,000 batches by 1.715x. This explicitly changes initial
placement from the older L2 runs. It does not erase PK's original capacity
failure, prove HLS-layout parity, or turn a prediction into FPGA evidence.
The checked export and two-panel preview are linked in that separate folder.

The new ResPR degree-prefix image passed its **same-clock 140/500/430-MHz**
G/R controls: G 10.957 vs. 19.166 ms; R Amazon +0.53%, skew -9.41% relative
to the public-source A4 port. These are one-sample, at-most-15%-slower checks,
not a reproduction of publication throughput or absolute +/-15% parity. The
150-MHz route missed timing; the two arms were both explicitly derated. The
original-host resident matrix is an earlier diagnostic. That host lost on PK (Spine
102.13 vs. G+R 75.73 ms). An independently qualified, bit-exact host correction
cache removes the per-batch full-graph correction rebuild; the five completed
retimes now favor Spine, **1.51x--13.07x**, against reused frozen G+R samples.
The LJ/R19 additions brought the corrected ResPR scope to seven cases.
The subsequent direct LJ08 pair passes both final oracles: **16.5773 ms
Spine vs. 330.583238 ms G+R**, or 19.94x for Spine. The eight-case range is
1.51x--19.94x. Earlier LJ08 pressure-guard aborts remain retained failures,
not measurements. The cache uses only the old graph/rank, prepares outside
the resident timer and reports that preparation separately. All eight have
zero nonempty propagation rounds, so they do not demonstrate propagation speedup. A separate
compact Flickr propagation case still loses (35.08 vs. 4.76 ms). The original
PK loss and Flickr loss both remain evidence, not omitted outliers.

The CC replacement route and its queued follow-ups are not measurements yet.
The [build-resume record](current_fpga/cc_resume_v1/README.md) preserves the
agent-caused guard interruption and corrected launch without rewriting the
old logs. The [PK capacity diagnostic](fresh_simulator/portable_fig8/diagnostics/pk_capacity_v1/README.md)
separately explains the fourth-batch hierarchy failure; PK has no accepted
Fig. 8 latency or ratio under that original L2 configuration.
The SSSP eight-row all-win result below is measured on its exact admitted
image; it must not be extrapolated to CC. Older sections below describe
earlier dated checkpoints and remain intact for provenance.

Author handoff, 2026-11-05. The paper and the November 3 data package are
unchanged. The plots do not represent one new hardware campaign. Keep their
evidence labels when reusing them.

| Plot | PDF / PNG | Inputs and scope |
| --- | --- | --- |
| G and R vs. public source | [PDF](figures/gr_source_comparison.pdf) / [PNG](figures/gr_source_comparison.png) | [Matched stage times](gr_source_comparison.csv), one U55C sample per arm. The SSSP/CC points use the exact banked baselines; the ResPR points are from the older packed-validity route. The dashed line is the public-source control |
| 7, latest SSSP FPGA | [PDF](figures/fig7_sssp_banked.pdf) / [PNG](figures/fig7_sssp_banked.png) | [Eight matched pairs](fig7_sssp_banked.csv), [raw receipt archive](fig7_sssp_banked_receipts.tar.gz). Same banked G+R image as the SSSP source controls. One sample per arm, no projections or timeouts |
| 7 | [PDF](figures/fig7_oct26_fpga.pdf) / [PNG](figures/fig7_oct26_fpga.png) | [Oct. 26 board data](../figure7_11_handoff_20261103/data/fig7_fpga_speedup.csv), 24 resident update-to-readback comparisons; no projections/timeouts. All eight ResPR rows have zero nonempty propagation rounds |
| 7, newer SSSP diagnostic | [PDF](figures/fig7_nov04_sssp_diagnostic.pdf) / [PNG](figures/fig7_nov04_sssp_diagnostic.png) | [Nov. 4 board data](../hardware_validation/r_retention_repair_20261103/sssp-resident-followup/README.md), six pairs; n/m means no measurement, not timeout. G and the two Amazon R screens passed, but AU R exceeded 15% on this specific image |
| 7, Nov. 5 FPGA diagnostic | [PDF](figures/fig7_nov05_fpga_diagnostic.pdf) / [PNG](figures/fig7_nov05_fpga_diagnostic.png) | [All 24 case statuses](fig7_nov05_diagnostic.csv) and [receipt index](fig7_nov05_diagnostic.json). One matched board sample per arm where admitted; crosses mark failed cases, blank slots have no admitted measurement. AU R is outside 15% |
| 7, legacy FullPR | [PDF](figures/fig7_fullpr_legacy.pdf) / [PNG](figures/fig7_fullpr_legacy.png) | [Three compact FPGA cases](../figure7_11_handoff_20261103/data/fig7_fullpr_legacy_not_refreshed.csv), older hardware and measurement contract; bars are medians, whiskers are observed ranges |
| 8 | [PDF](figures/fig8_one_batch_model.pdf) / [PNG](figures/fig8_one_batch_model.png) | [Setup-inclusive model](../figure7_11_handoff_20261103/README.md#figure-8-setup-inclusive-update-throughput): measured host preparation plus modeled device and transfer terms. Update only, one batch, older G path |
| 8, native diagnostic | [PDF](figures/fig8_one_batch_fpga_diagnostic.pdf) / [PNG](figures/fig8_one_batch_fpga_diagnostic.png) | [Earlier native setup checkpoint](../hardware_validation/r_retention_repair_20261103/paired-board-checkpoint/figure8.csv) (bars) and [direct-metadata host replay](fig8_direct_metadata.csv) (dots), one batch, four G metadata replicas. Orange marks earlier losses; Cap. means the G allocation did not fit |
| 9 | [PDF](figures/fig9_memory_hbm_model.pdf) / [PNG](figures/fig9_memory_hbm_model.png) | [Ratios](../figure7_11_handoff_20261103/data/fig9_memory_energy_rows.csv), [absolute per-arm bytes and pJ](../figure7_11_handoff_20261103/data/fig9_arms.csv). Simulated traffic and DRAMSim3 HBM energy, separate scales; not board power |
| 10 | [PDF](figures/fig10_simulator_breakdown.pdf) / [PNG](figures/fig10_simulator_breakdown.png) | [Eleven simulator executions](../figure7_11_handoff_20261103/data/fig10_normalized_breakdown_rows.csv), each stack normalized to 100% of that execution's cycles |
| 11 | [PDF](figures/fig11_realized_work_model.pdf) / [PNG](figures/fig11_realized_work_model.png) | [Predictions](../figure7_11_handoff_20261103/data/fig11_e2e_prediction_rows.csv) and [metrics](../figure7_11_handoff_20261103/data/fig11_e2e_metric_rows.csv), 24 fit + 17 unseen rows; all/real median APE 10.0%/58.1% against simulator output, not FPGA |

## What The G/R Plot Establishes

The [banked source-burst stage and board receipts](../hardware_validation/r_retention_repair_20261103/SSSP_STAGE_ADMISSION.md#banked-source-burst-follow-up)
supersede the earlier SSSP control on which AU R was outside 15%. All
three SSSP R controls are now within 15%, and G is faster in its matched
control. On that exact G+R image, Spine wins all eight resident SSSP
pairs, **2.03x--24.01x**. This is a replacement for the SSSP series only,
not a three-algorithm replacement. The prepared-batch wall time includes
host waits, relaunch and readback; initial frontier packing is outside
G+R's timer and the corresponding source-list construction is inside
Spine's. The archive includes clocks, logs and hash-pinned comparison
receipts. It does not duplicate the large final state dumps, input graphs,
host binaries or xclbins; their paths and hashes are in the receipts.

The following stage-control paragraphs describe the **older** previews in
the table above. The current degree-prefix ResPR G time and the corrected
resident checkpoint are linked at the top; do not use the old ResPR 7.27x
slowdown as the latest source-retention result.

G measures the first-to-last update-CU event span, including gaps between
shards but excluding input residency and final readback. The public GraSU
control updates PMA only. SSSP and CC are faster in the matched AU 131K
screen (7.023 and 7.364 ms vs. 18.369 ms); the older integrated ResPR
variant includes the device degree-update CU and takes 133.500 ms
(7.27x the public PMA-only time). That is a measurement of the augmented
path, not an isolated PMA slowdown or a result for the new degree-prefix
image.

R compares the actual adapter + integrated R with the public four-Little
ReGraph configuration (A4) on matched resident inputs; it excludes G,
initial upload and end-to-end host orchestration. AM+ is higher-activity
Amazon; Skew is the skewed-source fixture. The slowest observed ratios
are 1.135x (SSSP AU), 1.124x (CC AU) and 1.157x (older ResPR Skew);
the Amazon controls range from 0.917x to 0.966x. These are observed ratios,
not a blanket 15% parity claim or a reproduction of the original published
topology/throughput. The [dated stage receipts](../hardware_validation/r_retention_repair_20261103/README.md)
retain the earlier gate outcomes. The new degree-prefix ResPR image had
not produced a new G time at this checkpoint.

## Where Spine Loses

All 24 Oct. 26 main Fig. 7 rows and all six Nov. 4 SSSP diagnostic rows
favor Spine **on their measured images and batches**. For the latest
images, the latest checkpoint establishes eight SSSP wins and eight
zero-propagation ResPR wins; eight replacement CC pairs are still missing. These losses
and missing cases are relevant to interpretation and must not be omitted:

| Scope | Outcome |
| --- | --- |
| Nov. 5 resident CC FPGA, baseline passed on all declared controls | On full AU, the source-burst G+R takes **5.564 ms**, against the same **17.681 ms** Spine arm (G+R wins **3.18x**). Both execute one round, with the old graph converged and the same host-pack-to-final-readback boundary. See the [paired receipt and exact-image stage results](../hardware_validation/r_retention_repair_20261103/REMOTE_LINKS.md#cc-source-burst-board-results). This follow-up is newer than the diagnostic plot above. |
| Nov. 5 resident CC FPGA | On AU, G+R **5.450 ms** vs. Spine **17.681 ms** (G+R wins **3.24x**). Spine admission and relaxation each took about 8 ms; packing through batch residency took about 0.165 ms. All seven other cases, including LJ08, failed with row overflow on the old CC image. Each exceeds the image's 4,096-edge per-source row limit (R19 reaches 62,361). |
| Legacy compact FullPR FPGA | G+R wins on **AM 48.77x, WG 22.15x, FL 23.46x**, using the inverse median speedup. No current large-graph FullPR sweep |
| Fig. 8 native setup checkpoint | G wins on **AU/64 2.35x, AU/512 2.06x, AU/4096 2.53x, SU/512 1.69x**. Spine wins WK/512 1.03x and PK/512 1.99x. SO/512 has no four-copy pair. These are not ten-batch results |
| Fig. 8 intermediate host revisions | The early direct-directory AU/64 check still favored G by **1.61x**. The reused-directory host still lost AU/4096 by **1.10x**. The first card-0 AU/512 check with repaired G favored G by **1.054x**, then the [two-bank Spine replay](../hardware_validation/r_retention_repair_20261103/FIGURE_IMPACT.md#two-bank-spine-host-replay) flipped it to **1.21x** for Spine |
| Fig. 8 later direct-metadata host | Spine wins all six admitted [card-1 SSSP replays](../hardware_validation/r_retention_repair_20261103/FIGURE_IMPACT.md#latest-spine-host-direct-metadata-ownership), **1.04x–2.40x**, reusing the frozen G timings. SO/512 remains missing in the four-copy configuration; this is not a ten-batch sweep |
| Fig. 9 nonempty ResPR, fixed threshold | With the dense Spine Apply, [separate simulator cases](../figure7_11_handoff_20261103/data/fig9_respr_nonempty_dense.csv) favor G+R for latency on **Flickr 1.81x, AU540 1.54x, AU904 1.45x** and for modeled HBM energy on all three. The [sparse Apply candidate](../figure7_11_handoff_20261103/data/fig9_respr_sparse_candidate.csv) flips both AU cases to Spine wins (**11.57x** and **15.07x**) in simulation; G+R still wins Flickr by **1.59x**. The sparse candidate is not the plugin used for Figs. 10–11, and these are not FPGA results |
| Fig. 9 ResPR, stricter threshold | [Separate simulator diagnostic](../figure7_11_handoff_20261103/data/fig9_respr_threshold_comparison.csv): G+R is faster on **AU 5.24x, SU 4.13x, WK 4.72x** when propagation is forced by the stricter threshold. Not the plotted fixed-threshold energy rows |

Fig. 9's nine main pairs favor Spine for bytes and modeled energy under
their frozen assumptions. The later [directory-only sensitivity](../hardware_validation/r_retention_repair_20261103/fig9-directory-diagnostic.csv)
preserves that direction but changes magnitudes; it does not provide new
complete-image traffic or energy. Figures 10 and 11 do not compare Spine
against a baseline. Fig. 10 abbreviations: Syn = synthetic, FL = compact
Flickr, L1/L3/L5 = carry target levels 1/3/5. Zero-net uses the fallback
path on a delete/reinsert sequence, not a no-op optimization. The stage
shares are simulated attribution, not FPGA counters.

The Nov. 5 diagnostic contains nine measured pairs: Spine wins all eight
SSSP workloads (1.86x--23.82x), and G+R wins the one admitted CC workload
(AU). The diagnostic tests the replacement images despite the documented
AU R slowdown. It does not turn that screen into a 15% parity pass. The
SSSP rows use the resident update through final readback wall-time receipt;
the CC rows explicitly use host packing after old-state residency through
final readback. Both include host relaunch where present; do not aggregate
these two boundaries. The ResPR degree-prefix route and hardware controls
had not supplied an admitted pair for this snapshot. Figs. 8--11 retain the
version and evidence labels above; the new Fig. 7 measurements do not
refresh their input data.

The [CC replacement candidate](https://github.com/jayfeather9/spine-dynamic-graph/commit/2315cae)
raises the row limit to 65,536, validates insertions without materializing
the old row, and skips label propagation only if every net insertion
is internal to an old component. Its production-configuration C-model
tests passed. It is not a routed or board-measured result, and the seven
capacity failures and AU loss remain in this index.

The AU follow-up replaces only the Spine arm. Its current anchor is the
full AU receipt from the source-burst image that passed G and all three R
controls. The runner can also replay the older diagnostic matrix separately;
that replay preserves its original failed AU R retention screen.
From the simulator checkout, run the following on the original board host
once the candidate route is complete:

```sh
runner=spine_cycle_sim.experiments.original_regraph_execution.hardware.source_retention.cc_au_revision
python3 -m "$runner" --anchor "$anchor" "$anchor_sha" --candidate "$candidate" "$candidate_sha" --preflight
systemd-run --user --wait --collect --working-directory="$PWD" \
  -p MemoryMax=24G -p MemoryHigh=22G -p MemorySwapMax=0 -p OOMPolicy=kill \
  /usr/bin/python3 -m "$runner" --anchor "$anchor" "$anchor_sha" \
  --candidate "$candidate" "$candidate_sha" --run "$fresh_output_dir" --admission-wait-seconds 3600
```

`anchor` is the retained full AU pair receipt (or the older CC diagnostic matrix).
`candidate` is a JSON object with `host`, `image`, `manifest`, `link`,
`timing`, and `skew` file identities (`path`, `sha256`, `bytes`), the
Vitis output path `linked_image`, and the weighted build SHA `abi`.
The read-only preflight checks the original pair, candidate link and
manifest, and route timing/skew. The board run measures one sample and
requires the same workload, card, clocks, checked final labels, and
pack-to-readback timer. It writes `comparison.json` separately from the
published figure and records whether the exact G+R image passed the declared
stage controls. A single AU pair does not establish an eight-graph result.

If the route is on a separate build host, the
`spine_cycle_sim.experiments.original_regraph_execution.hardware.source_retention.cc_au_collect`
entry point can wait under the same memory cap. Pass the SSH endpoint
(`--remote`, `--port`), immutable build launch (`--root`, `--unit`,
`--invocation`, `--abi`), the same `--anchor`, and a fresh `--output`.
It hashes the selected artifacts at both ends before preflight and board
admission, and retains the route and original sample separately.

## Reproduce

From this directory in a full simulator checkout, run:

```sh
python -m pip install matplotlib==3.11.2
python render.py
```

Requires Python 3.11+ and LaTeX with `txfonts` and `dvipng`.
The Python renderer uses the grouped-bar construction from the supplied
[GraphyFlow_Plot.zip](../../../../../evaluation_refresh_20260810/figure7_10_handoff_v1/reference/GraphyFlow_Plot.zip)
(SHA-256 verified), reuses the previous TX Typewriter styling and Figure 10
renderer, and writes only PDF and PNG. Use `--output /path/to/figures`
to write a clean review copy without touching the tracked previews.

To regenerate the SSSP CSV and receipt archive on the run host, use
`python export_banked_sssp.py /path/to/sssp-resident-matrix-banked-v4/matrix.json --output /path/to/export`.
The exporter rejects incomplete matrices, mismatched receipt digests,
different clocks/images and failed stage gates.
