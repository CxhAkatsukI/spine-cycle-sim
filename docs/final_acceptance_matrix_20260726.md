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
| Spine weighted SSSP | Execution-driven shared core, dynamic fallback, SST/DRAMSim3, dual oracle | Implemented | Run final real-dataset matrix and freeze manifests |
| Spine Full PageRank | Timed Map/Reduce policy and SST vertical slice | Implemented | Run final real-dataset small-batch matrix |
| Spine thresholded residual PageRank | Timed signed-residual policy and SST vertical slice | Implemented | Run final real-dataset small-batch matrix |
| GraSU/ReGraph weighted SSSP | Normalized executable mode; native unit-weight mode; `ff13a67` weighted full-word HLS-aligned mode | Implemented | Broaden HLS-aligned workload coverage beyond one fixture |
| GraSU/ReGraph Full PageRank | Normalized PMA-native and partitioned dynamic mode | Normalized only | Define and implement the HLS-aligned PageRank profile or label comparison normalized |
| GraSU/ReGraph thresholded residual PageRank | Normalized PMA-native and multi-partition mode | Normalized only | Define and implement the HLS-aligned residual profile or label comparison normalized |
| Differential correctness | Shared dynamic fixtures and per-run architecture/mathematical oracles | Partial | Every final experiment row must emit zero mismatches; add deletion/increase cases to final real datasets |
| End-to-end small-batch performance | 73-pair normalized comparison plus native/HLS vertical slices | Partial | Freeze datasets from GraSU/Dynamic-ACTS practice and run final HLS-aligned matrix |
| Update throughput | Timed Spine maintenance and GraSU PMA update counters | Partial | Report logical and physical edge/s separately on common real small batches |
| Memory behavior | Per-component bytes/requests, AXI stalls, DRAM reads/writes/ACT/PRE, sparse channel binding | Partial | Add common sequential/random classification and per-algorithm tables |
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

## Immediate Next Gate

Build a multi-workload HLS-aligned weighted-SSSP matrix around
`scripts/run_sst_grasu_regraph_hls_weighted.py`: insertion, exact deletion,
weight decrease, weight increase, mixed update, sparse long-diameter, dense
fan-in, and source-window boundary cases. Each case must compare the simulator
to the Python lowering/Dijkstra oracle and retain logical/physical update and
memory ledgers. This closes the single-fixture limitation before extending the
same architecture profile to PageRank.
