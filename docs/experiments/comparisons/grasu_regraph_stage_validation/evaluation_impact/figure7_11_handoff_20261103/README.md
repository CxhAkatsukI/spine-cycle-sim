# Figures 7--11 Data Handoff

Data-only delivery, 2026-11-03. **The paper is unchanged.** Figures 10--11
come from new simulator executions and a new fit, not a redraw of frozen
August measurements. Figures 7--9 collect existing, explicitly versioned
evidence. This directory is an evidence package, not one newly calibrated
five-figure experiment. No new plot previews are required for this delivery.

## Start Here

| Figure | Plot-ready data | Scope and evidence |
| --- | --- | --- |
| 7 | [FPGA times and speedups](data/fig7_fpga_speedup.csv) | Eight datasets x SSSP/CC/ResPR, 24 pairs; October 26 single-pass FPGA runs |
| 8a | [Cross-dataset throughput](data/fig8_update_cross_dataset.csv) | AU/SU/WK/SO/PK, one 512-update batch each |
| 8b | [Batch sensitivity](data/fig8_update_batch_sensitivity.csv) | AU, one batch of 64/512/4096 updates |
| 9a--b | [Bytes and HBM-energy ratios](data/fig9_memory_energy_rows.csv) | AU/SU/WK x SSSP/CC/ResPR, nine simulator pairs |
| 10 | [Absolute ten-stage cycles](data/fig10_stage_rows.csv), [normalized five-group values](data/fig10_normalized_breakdown_rows.csv) | Eleven newly executed cases; simulator prediction |
| 11 | [Observed/predicted cycles](data/fig11_e2e_prediction_rows.csv), [metrics](data/fig11_e2e_metric_rows.csv), [model](data/fig11_e2e_model.json) | New 41-row fit/evaluation; 24 calibration, 17 held out |

[Per-arm Figure 8 data](data/fig8_arms.csv) and
[per-arm Figure 9 data](data/fig9_arms.csv) retain absolute cycles, traffic,
host contributions and energy components. Figure 11 also includes
[realized work and stages](data/fig11_latency_rows.csv) and
[per-stage regression diagnostics](data/fig11_regression_rows.csv).
See the [test report](TEST_REPORT.md), [fresh-run summary](data/fig10_11_fresh_summary.json)
and [package index](provenance/package.json) before using a headline ratio.

## Figure 7: Resident FPGA Latency

Ratio is `gr_wall_ms / spine_wall_ms`: above one means Spine is faster.
Use all eight datasets in the supplied order: AU, SU, WK, SO, PK, LJ, LJ08,
R19. Three adjacent bars per dataset can encode SSSP, CC and ResPR. There
are no missing/timeout/projected values in these 24 admitted pairs.

Both sides begin with the old graph and its converged state resident, apply
the same batch, and run to the new stopping condition. The wall-time window
includes host launch/wait, inter-round relaunch and final readback. Initial
graph/PMA preparation, metadata replication, initial upload, old convergence
and correctness oracles are outside both windows. G's four cached metadata
replicas are prepared before this resident measurement. These are **one run
per arm**, not averages or medians. The source report, admission audit,
clocks, stdout and resource records are retained.

SSSP and CC run at 150 MHz on both sides; ResPR uses G+R at 149 MHz and
Spine at 150 MHz. Ratios use measured wall time, with no frequency scaling.
**All eight ResPR batches terminate without nonempty residual propagation
at the fixed threshold.** This is a valid stopping case, not evidence of
the same speedup on propagating ResPR workloads.

[Legacy compact FullPR](data/fig7_fullpr_legacy_not_refreshed.csv) is supplied
separately for reference. Its three older compact FPGA cases and older
repetition policy are not refreshed by this work; do not combine them into
a claim of four current algorithms on eight large graphs.

## Figure 8: Setup-Inclusive Update Throughput

**This is one batch, not ten batches.** The frozen predecessor's CSV also
records `batch_count=1`; no resident ten-batch result has been inferred or
fabricated. Cross-dataset and batch-sweep panels share AU/512, leaving seven
unique pairs. Only update processing is timed, not ReGraph propagation.

```text
T = median(host layout construction + batch preparation, five Release runs)
  + (logical initial upload bytes + batch upload bytes) / 12 GB/s
  + 10 us launch/synchronization
  + update-only device cycles / 150 MHz
throughput = logical_updates / T
speedup = throughput_Spine / throughput_G
```

Initial preparation and upload are charged once. Host runs are CPU-pinned;
the original summary and evidence capsule identify binaries, flags and
affinity. The CPU work constructs the simulator-side images, not a timed
native XRT host application. Parsing, independent oracles, runtime buffer
allocation and readback are outside this host window. Logical uploads are
not padded XRT BO transfers. Transfer rate and launch time are assumptions.

The October 23 G configuration uses shared metadata and natural 64K
destination shards. It is **not** October 26's cached/replicated-metadata
FPGA G configuration from Figure 7. On these cases the setup-inclusive
advantage is dominated by initial preparation, not a faster Spine update
kernel. The original `baseline_admitted=false` status is retained: this
package does not establish original-publication performance reproduction.
The two panels need legends appropriate to their own encodings.

## Figure 9: Accepted Bytes And Modeled HBM Energy

Use SSSP, CC and ResPR as algorithm groups; AU/SU/WK bars can touch within
each group, with one dataset-color legend above. No vertical group-divider
lines are needed. Give panels independent y axes: absolute byte totals are
in the pair/arm tables, and absolute energy is in pJ in the arm table. A
ratio plot must instead label its y axis `G+R / Spine`; it is not a byte unit.

Accepted bytes equal accepted read plus write bytes. The energy ratio is
computed from DRAMSim3 total subsystem energy, **not bytes times a constant**.
These runs include background/refresh energy for all 32 budgeted channels;
the old handoff used a different bound-channel energy scope. Host and
off-chip upload energy are excluded. This is not FPGA board power or total
accelerator/ASIC energy. Different device durations and this accounting
change can alter energy ratios without changing the byte ratio similarly.

SSSP/CC rows come from the three-algorithm October collection; only ResPR
rows are replaced with its explicit fixed-`epsilon=1e-6` follow-up. The
[threshold comparison](data/fig9_respr_threshold_comparison.csv) preserves
the earlier `1e-5/V` results separately. Both fixed-threshold arms start at
the same old rank; AU/SU/WK have zero active propagation and unchanged final
rank arrays. Spine correction is oracle-directed timed replay, not proof
of an independently routed correction pipeline. Original-G and original
warm-residual-R timing admission remain open.

Do not omit the separate nonempty-propagation evidence when generalizing:
[dense-path results](data/fig9_respr_nonempty_dense.csv) and
[sparse-Apply candidate](data/fig9_respr_sparse_candidate.csv) cover FL,
AU540 and AU904. G+R wins all three dense comparisons; the sparse candidate
changes G+R/Spine to 0.630, 11.572 and 15.069, respectively. These supplemental
rows are **not** spliced into the nine-pair Figure 9 table. The sparse
candidate is also **not wired into the SST plugin used for Figures 10--11**.

## Figure 10: Fresh Normalized Stage Prediction

All eleven rows were executed again using one frozen plugin and derived
`candidate10_one_pass` maintenance profiles. No old cycles are copied.
The data retain absolute ten-stage cycles and five grouped percentages:

| Display group | Included stage fields |
| --- | --- |
| Maint. | transfer, reduction, carry, directory |
| Seed/pub. | seed and switch/publication |
| Resolve | reader exclusive critical-path time |
| App | compute exclusive critical-path time |
| Drain | drain and synchronization |

**Each stacked bar is normalized to its own total, summing to 100%.**
The ten stages also sum exactly to the absolute total. Reader/compute
overlap is assigned to the later finisher rather than counted twice;
unclassified completion gaps can enter drain. This is overlap-aware
simulator attribution, not ten independently measured FPGA timers.
PR-correction aggregate time is charged to seed/publication by this ledger.

| Group | Labels and precise meaning |
| --- | --- |
| ZN | Syn: synthetic delete/reinsert batch with an identical final snapshot |
| SI | AU/SU/WK: shallow weighted-SSSP insertions, eight updates each |
| Carry | L1/L3/L5: fixtures forcing carry target levels 1/3/5; eight update records |
| PR-corr | FL: Flickr correction u8 with nonempty propagation; SU/WK: compact residual-PR u8 |
| Del | Syn: synthetic deletion requiring SSSP fallback |

ZN has two logical undirected mutations/four physical records. The runner
uses the deletion/full-rebuild path even though the final graph is unchanged;
it is **not** a no-repair optimized zero-net measurement. L1/L3/L5 are carry
target levels, not dataset names. FL denotes the 2,552-vertex, 8,192-edge
reciprocal sink-free Flickr slice. These cases retain the predecessor's
case identities, not the complete large graphs from Figure 7.

The source profiles retain explicit timing assumptions, including reader
control and fallback setup terms. Derived profiles and all exact commands
are archived. These are model assumptions, **not newly calibrated stages**.
The current SST residual path is the dense default; do not claim identity
with the separate sparse-Apply candidate or complete latest FPGA parity.

## Figure 11: Fresh Fit And Holdout

The predeclared matrix contains 42 executions: 25 carry fixtures, 12 compact
real-graph/algorithm cases, three Flickr PR cases, one deletion and one ZN.
ZN is Figure-10-only and excluded from fitting. The other 41 retain the
predecessor's immutable role assignments: 18 synthetic-calibration, six
trace-calibration, 17 holdout. Of the holdouts, ten are carry fixtures and
seven are real-input cases. The historical role name `synthetic_calibration`
also includes the Flickr u1/u64 calibration experiments; dataset kind and
execution identity remain explicit. No holdout enters fitting.

The model has eight realized-work features plus an intercept, with
nonnegative coordinate descent and inverse-observed-cycle weighting, as in
the existing analyzer. The calibration matrix is rank 9/9. Coefficients,
iterations and all feature rows are provided. The simulator is not changed
by this regression; it predicts its output, not the other way around.

| Population | N | Predictive R2 | Median APE | Maximum APE |
| --- | ---: | ---: | ---: | ---: |
| Calibration | 24 | 0.999961 | 10.48% | 48.06% |
| All holdout | 17 | 0.980277 | 10.00% | 89.07% |
| Real-input holdout only | 7 | 0.977618 | 58.08% | 89.07% |

High predictive R2 does **not** establish accurate relative prediction for
small/real cases; large values dominate the squared-error metric. The
real-input percentage error remains substantial. The per-stage diagnostic
OLS R2 values are also recomputed: across supported rows, carry 0.991424,
directory 0.149143, seed 0.745392. These are descriptive one-feature fits,
not per-stage FPGA calibration and not substitutes for the E2E holdout.
The old 0.996/0.998/0.979 values must not be reused.

For a new scatter plot, label x as **Observed simulator cycles**, y as
**Model-predicted cycles**, distinguish calibration/holdout, and report both
holdout populations. Do not label simulated observations as FPGA measurements.

## Evidence And Reproduction

`manifest.json` hashes every delivered file. `provenance/package.json`
indexes the new raw archive, its input copies, the FPGA archive and retained
preflight failure. Large gzip archives are split into numbered parts below
GitHub's per-file limit; concatenate in index order before extraction.
Every member and every part has a SHA256. Existing Figure 8--9 raw capsules
are referenced by repository-relative path and SHA256 rather than duplicated;
clone this repository for the full evidence chain.

Fresh plugin SHA256:
`73688191621482a533176687cf28b7b19e650580041e74f94e9efa6babaff323`.
The identity records base simulator commit `60069a1c8367c6e4453fb736aca1b5547b0bfe46`,
GCC 15.2.0, numerical source hashes, frozen matrix and memory settings. The
delivery commit additionally contains the new campaign code. Toolchain and
SST/DRAMSim3 binaries are external dependencies; fresh numerical sources and
build configuration are not claimed to be a portable binary environment.

The implementation is the repository package
`spine_cycle_sim.experiments.evaluation_impact.figure_refresh.realized_work`.
It separates matrix preparation, bounded execution, admission, analysis,
packaging and offline verification. From the repository root:

```bash
make -C cpp/sst -j2 BUILD_DIR=/absolute/fresh/plugin \
  DRAMSIM3_ROOT=/absolute/dramsim3
python3 -m spine_cycle_sim.experiments.evaluation_impact.figure_refresh.realized_work.run \
  --out-dir /absolute/fresh/campaign --lib-dir /absolute/fresh/plugin
python3 -m spine_cycle_sim.experiments.evaluation_impact.figure_refresh.realized_work.analysis \
  --campaign /absolute/fresh/campaign
python3 -m spine_cycle_sim.experiments.evaluation_impact.figure_refresh.realized_work.verify \
  --package docs/experiments/comparisons/grasu_regraph_stage_validation/evaluation_impact/figure7_11_handoff_20261103 \
  --repository .
```

The default matrix expects the external compact inputs named in
`provenance/fig10_11_matrix.json`; copies are in the raw archive under
`inputs/<sha256>/<basename>`. Restore these paths or deliberately create a
new relocated matrix with newly recorded identity. Do not edit the frozen
matrix to reuse an old identity. Profiles live under `profiles/`, and each
execution's raw results, manifests, stdout/stderr and resources live under
`runs/<execution_id>/` inside the archive. Only already admitted raw outputs
from this same frozen campaign can be reused by its resume path.

This handoff supports redrawing with visible scope limitations. It does not
establish original-publication G/R performance reproduction, complete HLS
architecture parity, FPGA stage calibration, or a ten-batch resident result.
