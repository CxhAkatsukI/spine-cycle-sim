# Delta.hls optimization execution contract

Date: 2026-07-27  
Branch: `codex/deltahls-paper-optimization`

## Objective

This milestone freezes the rules for the final Delta.hls/Spine optimization
and evaluation before any optimized holdout result is observed. The engineering
target is at least `1.05x` Spine E2E speedup for each of weighted SSSP, Full
PageRank, and thresholded residual PageRank on the primary resource-normalized
multi-partition matrix. The paper claim remains conditional on sparse touched
sources and localized propagation; broad propagation, deep carries, and full
fallback are required reported boundaries rather than discarded outliers.

The machine-readable source of truth is
`configs/contracts/deltahls_optimization_execution_v1.json`.

## Frozen comparator

The primary comparator is conversion-free GraSU PMA plus ReGraph with
destination partitioning and a finite work-conserving dispatcher. The number
of complete reader/map/gather/merge/apply pipelines is selected from synthesis,
not timing results. One pipeline is synthesized first; the largest `K` that
fits the shared U55C, 23-pseudo-channel budget, 150 MHz target, and 80% device
resource ceiling is frozen before holdout. `K=1/2/4` remain scalability points.

An HLS-native multi-CU profile is secondary evidence. It checks that the
normalized profile does not weaken GraSU+ReGraph, but it is not silently called
an iso-resource result.

## Spine optimization boundary

The ratio-2 hierarchy, 16 destination partitions, 11 levels, source-ordered
runs, signed latest-view resolver, and epoch-tagged atomic publication remain
unchanged. Allowed optimizations are finite and synthesizable: 64-byte request
coalescing, state/metadata caches, AXI outstanding/reorder changes, bounded
prefetch/double buffering, duplicate replay suppression, chunked fallback,
family/level overlap, and device-side active discovery.

Ideal storage, future knowledge, unmeasured host work, workload-specific paths,
algorithm changes, and replacing the hierarchy with a flat snapshot or PMA are
forbidden. Every added queue or cache must expose capacity, occupancy, hit,
stall, traffic, and resource evidence.

## Calibration, holdout, and stopping

Synthetic microbenchmarks and three real slices are calibration inputs. Two
unseen real slices plus the multi-partition large slices are holdout. Ideal
ablation may select at most two implementation directions, producing at most
`opt-v1` and `opt-v2`. Profiles and capacities are committed before holdout;
holdout failure cannot be repaired in place under the same profile ID.

The success gate for each algorithm is:

- all correctness and conservation checks pass;
- E2E speedup geometric mean is at least `1.05x`;
- Spine wins at least 60% of workload pairs; and
- reasonable HBM, FIFO, and outstanding sensitivity does not invert the
  primary ranking.

After `opt-v2`, losses remain evidence. Full PageRank is a required full-scan
and recomputation benchmark, not the primary incremental PageRank claim.

## Workloads and scale

Batch eight is primary; batches one and 64 are sensitivity points. Real update
windows are selected from graph/update statistics without architecture timing
results and are stratified as localized sparse, cancellation-heavy,
high-degree/deep-carry, and broad-propagation/fallback.

Two- and four-partition real-topology workloads are mandatory. The four-
partition target is at least 200K vertices and one million edges, with actual
work in every partition. A complete unsliced dataset is run when measured host
runtime indicates it is practical. A slice is never labeled a full-dataset
result, and no run reduces iterations, weakens epsilon, or omits comparator work
to meet the 30-minute engineering target.

## Evidence gates

Every performance row is fail-closed on architecture and mathematical oracles,
cross-system graph/algorithm state, degree and active-set state, FIFO/AXI
request conservation, backend-to-DRAM command closure, and final drain.

Each optimization requires individual and combined ablation plus HBM
latency/bandwidth `+/-20%` and FIFO/outstanding `0.5x/2x` sensitivity. Stall
attempts are diagnostic events and are not added directly as cycle counts.

## Implementation cost

FPGA evidence includes C simulation, synthesis resources, II/latency, target
and estimated frequency, and one final implementation attempt with routed
utilization and WNS/TNS when complete.

In addition, both systems use the same standard-cell synthesis and CACTI/SRAM
macro assumptions to produce a projected accelerator-core area split into
logic/control/interconnect, state memory, metadata memory, and FIFO/cache.
HBM stacks/PHY, PCIe/FPGA shell, and host are excluded. This projection is not
a fabricated-chip or complete ASIC claim.

## Reproduction

Validate the contract before running optimized holdout experiments:

```bash
cd /home/chuxiao/spine-cycle-sim-publication
python3 -m json.tool \
  configs/contracts/deltahls_optimization_execution_v1.json >/dev/null
git diff --check
```
