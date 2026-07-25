# Final Simulator Acceptance Matrix

Date: 2026-07-26

## Rule

The final artifact is accepted only when every required row below is closed by
a reproducible command, a machine-readable manifest, an independent
correctness oracle, and an explicit claim class. A normalized or projected run
cannot silently satisfy an HLS-aligned requirement.

## Current Status

| Requirement | Current evidence | Status | Remaining gate |
| --- | --- | --- | --- |
| Spine weighted SSSP | Execution-driven shared core, dynamic fallback, SST/DRAMSim3, dual oracle, and 9-case real-compact matrix | Implemented | Scale beyond compact slices and split aligned maintenance from compute traffic |
| Spine Full PageRank | Timed Map/Reduce policy, SST vertical slice, and 9-case real-compact matrix | Implemented | Scale beyond compact slices |
| Spine thresholded residual PageRank | Timed signed-residual policy, shared dynamic-update contract, and 9-case real-compact matrix | Implemented | Scale beyond compact slices |
| GraSU/ReGraph weighted SSSP | Normalized executable mode; native unit-weight mode; `ff13a67` weighted full-word HLS-aligned mode; 10 synthetic plus 9 real-compact dynamic cases | Implemented | Scale beyond compact slices and compare with hw/hw_emu timing evidence |
| GraSU/ReGraph Full PageRank | Normalized modes plus executable ff13a67 full-word HLS-equivalent proposed profile, dual oracle, and 9-case real-compact matrix | Implemented | Scale beyond compact slices |
| GraSU/ReGraph thresholded residual PageRank | Executable ff13a67 full-word proposed profile, dual oracle, and 9-case real-compact matrix | Implemented | Scale beyond compact slices |
| Differential correctness | Per-run dual oracles plus 9/9 cross-system matches for weighted SSSP, Full PageRank, and residual PageRank | Partial | Preserve fail-closed checks on full-dataset experiments |
| End-to-end small-batch performance | 9-pair real-compact HLS-profile matrices for weighted SSSP, Full PageRank, and residual PageRank | Partial | Add publication-scale datasets and batch sweeps |
| Update throughput | Common real-compact batches report user mutations and physical records for Spine maintenance and GraSU PMA | Partial | Sweep batch size/density on full-scale inputs and validate against hw |
| Memory behavior | Common accepted-request bytes and per-initiator/per-operation contiguous/repeated/discontinuous classification; 54 system rows and 27 paired rows | Partial | Add physical burst amplification/row-locality tables and split weighted-Spine maintenance from compute |
| Energy by component | DRAMSim3 active-channel energy and selected CACTI evidence | Partial | Complete on-chip activity-to-energy mapping; keep idle-channel assumptions explicit |
| Area and timing | Existing routed Spine/native GraSU evidence | Partial | Add reports for the final HLS-equivalent design and map simulator components to reports |
| Dense batches | Synthetic dense/pathological fixtures exist | Partial | Sweep batch density/size and report crossover and failure/capacity boundaries |
| Large-graph runtime | Sparse HBM binding and native stress runtime evidence | Partial | Run at least one publication-scale graph per required algorithm within the agreed tens-of-minutes budget |
| Ablation | What-if/profile mechanisms exist | Optional/open | Run only after required rows close |
| Scalability | Projected profiles are fail-closed `profile_only` | Optional/open | Model resource-scaled kernels/BRAM/URAM and report non-linear contention before claiming speedup |

## Required Final Experiments

1. Correctness is checked inside every experiment, not inferred from a separate
   smoke test. Store architecture-oracle and mathematical-oracle mismatch
   counts in every row.
2. End-to-end results use small insertion/deletion batches on common real
   datasets. PageRank can be the first complete matrix while SSSP automatic
   active-set repair is finalized.
3. Update results report both logical updates per second and physical PMA
   operations per second. Weight changes in the `ff13a67` profile count as two
   physical operations.
4. Memory results separate bytes, requests, bursts, row activity, sequential
   versus random access, and contention/stall cycles for update and compute.
5. Energy, area, and timing rows name their source: DRAMSim3, CACTI, HLS/Vivado,
   or projected. No source may be promoted to total-accelerator evidence by
   implication.
6. Dense-batch sweeps include the sparse regime, crossover, saturation, and
   capacity/failure boundary.
7. The final large-graph runner records host wall time and must complete in the
   agreed tens-of-minutes range without skipping correctness or memory events.

## Closed Synthetic Gate

The 10-case `ff13a67` weighted-SSSP matrix now covers insertion, exact
deletion, weight decrease/increase, mixed update, four-round convergence,
dense fan-in, the 4,096-source-window boundary, multi-segment PMA variants,
and deterministic reorder ties. All cases pass the architecture and Dijkstra
oracles. See `docs/grasu_hls_weighted_matrix_20260726.md`.

## Closed Real-Compact Weighted Gate

The 9-pair matrix now covers Amazon-2008, web-Google, and soc-Flickr compact
real-edge slices with insertion, deletion, and explicit weight replacement.
All 18 system rows and all cross-system distance vectors pass. The timing
window, profile clocks, update throughput, aligned backend requests, stalls,
and runtime are frozen in
`docs/hls_weighted_real_compact_comparison_20260726.md`.

## Closed Real-Compact Full PageRank Gate

The common nine-pair matrix covers the same three real compact slices and
insert/delete/weight-change batches. All 18 system rows pass dual oracles and
all cross-system rank vectors match. Profile-clock-adjusted E2E results favor
GraSU/ReGraph by 1.282x geometric mean, while the component breakdown exposes
a 340x update advantage and near-parity compute. See
`docs/hls_full_pagerank_real_compact_comparison_20260726.md`.

## Closed Real-Compact Residual PageRank Gate

The common nine-pair residual matrix validates rank, residual, and per-round
frontier equivalence. Spine wins all three Amazon cases, while GraSU/ReGraph
wins all six Web-Google and Flickr cases; overall GraSU/ReGraph is 1.116x
faster by geometric mean. See
`docs/hls_residual_pagerank_real_compact_comparison_20260726.md`.

## Immediate Next Gate

Complete matched component-energy/PPA evidence next, then close the
publication-scale checkpoint loader/runtime gate and dense-batch sweep.
Accepted-request volume and locality are now comparable for all three
algorithms; DRAM burst amplification, row-hit behavior, weighted-Spine's
internal maintenance/compute split, and total energy ratios remain open.
