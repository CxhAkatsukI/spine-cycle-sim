# G/R Source Controls and Evaluation Plots

Author handoff, 2026-11-05. The paper and the November 3 data package are
unchanged. The plots do not represent one new hardware campaign. Keep their
evidence labels when reusing them.

| Plot | PDF / PNG | Inputs and scope |
| --- | --- | --- |
| G and R vs. public source | [PDF](figures/gr_source_comparison.pdf) / [PNG](figures/gr_source_comparison.png) | [Matched stage times](gr_source_comparison.csv), one U55C sample per arm; dashed line is the public-source control |
| 7 | [PDF](figures/fig7_oct26_fpga.pdf) / [PNG](figures/fig7_oct26_fpga.png) | [Oct. 26 board data](../figure7_11_handoff_20261103/data/fig7_fpga_speedup.csv), 24 resident update-to-readback comparisons; no projections/timeouts. All eight ResPR rows have zero nonempty propagation rounds |
| 7, newer SSSP diagnostic | [PDF](figures/fig7_nov04_sssp_diagnostic.pdf) / [PNG](figures/fig7_nov04_sssp_diagnostic.png) | [Nov. 4 board data](../hardware_validation/r_retention_repair_20261103/sssp-resident-followup/README.md), six pairs; n/m means no measurement, not timeout. G and the two Amazon R screens passed, but AU R exceeded 15% on this specific image |
| 7, legacy FullPR | [PDF](figures/fig7_fullpr_legacy.pdf) / [PNG](figures/fig7_fullpr_legacy.png) | [Three compact FPGA cases](../figure7_11_handoff_20261103/data/fig7_fullpr_legacy_not_refreshed.csv), older hardware and measurement contract; bars are medians, whiskers are observed ranges |
| 8 | [PDF](figures/fig8_one_batch_model.pdf) / [PNG](figures/fig8_one_batch_model.png) | [Setup-inclusive model](../figure7_11_handoff_20261103/README.md#figure-8-setup-inclusive-update-throughput): measured host preparation plus modeled device and transfer terms. Update only, one batch, older G path |
| 8, native diagnostic | [PDF](figures/fig8_one_batch_fpga_diagnostic.pdf) / [PNG](figures/fig8_one_batch_fpga_diagnostic.png) | [Earlier native setup checkpoint](../hardware_validation/r_retention_repair_20261103/paired-board-checkpoint/figure8.csv), one batch, four G metadata replicas. Orange bars mark losses; Cap. means the G allocation did not fit. Same-card host improvements are reported separately below |
| 9 | [PDF](figures/fig9_memory_hbm_model.pdf) / [PNG](figures/fig9_memory_hbm_model.png) | [Ratios](../figure7_11_handoff_20261103/data/fig9_memory_energy_rows.csv), [absolute per-arm bytes and pJ](../figure7_11_handoff_20261103/data/fig9_arms.csv). Simulated traffic and DRAMSim3 HBM energy, separate scales; not board power |
| 10 | [PDF](figures/fig10_simulator_breakdown.pdf) / [PNG](figures/fig10_simulator_breakdown.png) | [Eleven simulator executions](../figure7_11_handoff_20261103/data/fig10_normalized_breakdown_rows.csv), each stack normalized to 100% of that execution's cycles |
| 11 | [PDF](figures/fig11_realized_work_model.pdf) / [PNG](figures/fig11_realized_work_model.png) | [Predictions](../figure7_11_handoff_20261103/data/fig11_e2e_prediction_rows.csv) and [metrics](../figure7_11_handoff_20261103/data/fig11_e2e_metric_rows.csv), 24 fit + 17 unseen rows; all/real median APE 10.0%/58.1% against simulator output, not FPGA |

## What The G/R Plot Establishes

G measures the first-to-last update-CU event span, including gaps between
shards but excluding input residency and final readback. The public GraSU
control updates PMA only. SSSP and CC are faster in the matched AU 131K
screen (7.298 and 7.045 ms vs. 18.369 ms); the older integrated ResPR
variant includes the device degree-update CU and takes 133.500 ms
(7.27x the public PMA-only time). That is a measurement of the augmented
path, not an isolated PMA slowdown or a result for the new degree-prefix
image.

R compares the actual adapter + integrated R with the public four-Little
ReGraph configuration (A4) on matched resident inputs; it excludes G,
initial upload and end-to-end host orchestration. AM+ is higher-activity
Amazon; Skew is the skewed-source fixture. The slowest observed ratios
are 1.214x (SSSP AU), 1.209x (CC AU) and 1.157x (ResPR Skew);
the Amazon controls range from 0.932x to 1.007x. These are observed ratios,
not a blanket 15% parity claim or a reproduction of the original published
topology/throughput. The [dated stage receipts](../hardware_validation/r_retention_repair_20261103/README.md)
retain the earlier gate outcomes. The new degree-prefix ResPR image had
not produced a new G time at this checkpoint.

## Where Spine Loses

All 24 Oct. 26 main Fig. 7 rows and all six Nov. 4 SSSP diagnostic rows
favor Spine **on their measured images and batches**. This does not
establish the outcome on the replacement images. These losses and missing
cases are relevant to interpretation and must not be omitted:

| Scope | Outcome |
| --- | --- |
| Legacy compact FullPR FPGA | G+R wins on **AM 48.77x, WG 22.15x, FL 23.46x**, using the inverse median speedup. No current large-graph FullPR sweep |
| Fig. 8 native setup checkpoint | G wins on **AU/64 2.35x, AU/512 2.06x, AU/4096 2.53x, SU/512 1.69x**. Spine wins WK/512 1.03x and PK/512 1.99x. SO/512 has no four-copy pair. These are not ten-batch results |
| Fig. 8 subsequent same-card AU host checks | With the two-bank Spine host, [AU/512 changes to 1.21x in favor of Spine](../hardware_validation/r_retention_repair_20261103/FIGURE_IMPACT.md#two-bank-spine-host-replay). The direct-directory AU/64 follow-up still favors G by **1.61x**. Neither point replaces a full comparable sweep |
| Fig. 9 nonempty ResPR, fixed threshold | [Separate simulator cases](../figure7_11_handoff_20261103/data/fig9_respr_nonempty_dense.csv) favor G+R for latency on **Flickr 1.81x, AU540 1.54x, AU904 1.45x** and for modeled HBM energy on all three. [Sparse Spine Apply](../figure7_11_handoff_20261103/data/fig9_respr_sparse_candidate.csv) narrows, but does not reverse, these gaps |
| Fig. 9 ResPR, stricter threshold | [Separate simulator diagnostic](../figure7_11_handoff_20261103/data/fig9_respr_threshold_comparison.csv): G+R is faster on **AU 5.24x, SU 4.13x, WK 4.72x** when propagation is forced by the stricter threshold. Not the plotted fixed-threshold energy rows |

Fig. 9's nine main pairs favor Spine for bytes and modeled energy under
their frozen assumptions. The later [directory-only sensitivity](../hardware_validation/r_retention_repair_20261103/fig9-directory-diagnostic.csv)
preserves that direction but changes magnitudes; it does not provide new
complete-image traffic or energy. Figures 10 and 11 do not compare Spine
against a baseline. Fig. 10 abbreviations: Syn = synthetic, FL = compact
Flickr, L1/L3/L5 = carry target levels 1/3/5. Zero-net uses the fallback
path on a delete/reinsert sequence, not a no-op optimization. The stage
shares are simulated attribution, not FPGA counters.

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
