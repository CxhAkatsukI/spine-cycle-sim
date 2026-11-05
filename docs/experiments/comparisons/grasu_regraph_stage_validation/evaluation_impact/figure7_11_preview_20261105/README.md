# G/R Source Controls and Evaluation Plots

Author handoff, 2026-11-05. The paper and the November 3 data package are
unchanged. The plots do not represent one new hardware campaign. Keep their
evidence labels when reusing them.

| Plot | PDF / PNG | Inputs and scope |
| --- | --- | --- |
| G and R vs. public source | [PDF](figures/gr_source_comparison.pdf) / [PNG](figures/gr_source_comparison.png) | [Matched stage times](gr_source_comparison.csv), one U55C sample per arm; dashed line is the public-source control |
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

The AU follow-up can replace only the Spine arm of the Nov. 5 diagnostic.
The original G+R sample and its failed AU R retention screen are preserved.
From the simulator checkout, run the following on the original board host
once the candidate route is complete:

```sh
runner=spine_cycle_sim.experiments.original_regraph_execution.hardware.source_retention.cc_au_revision
python3 -m "$runner" --anchor "$anchor" "$anchor_sha" --candidate "$candidate" "$candidate_sha" --preflight
systemd-run --user --wait --collect --working-directory="$PWD" \
  -p MemoryMax=24G -p MemoryHigh=22G -p MemorySwapMax=0 -p MemoryOOMGroup=yes \
  /usr/bin/python3 -m "$runner" --anchor "$anchor" "$anchor_sha" \
  --candidate "$candidate" "$candidate_sha" --run "$fresh_output_dir" --admission-wait-seconds 3600
```

`anchor` is the retained CC diagnostic matrix named in the receipt index.
`candidate` is a JSON object with `host`, `image`, `manifest`, `link`,
`timing`, and `skew` file identities (`path`, `sha256`, `bytes`), the
Vitis output path `linked_image`, and the weighted build SHA `abi`.
The read-only preflight checks the original pair, candidate link and
manifest, and route timing/skew. The board run measures one sample and
requires the same workload, card, clocks, checked final labels, and
pack-to-readback timer. It writes `comparison.json` separately from the
published figure; it is still a diagnostic, not admission for parity.

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
