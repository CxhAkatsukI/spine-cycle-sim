# GraSU + ReGraph Implementation

The ported baseline connects a GraSU PMA update stage to a PMA-native edge
adapter and ReGraph-style compute. Its routed configuration must not be
confused with the original ReGraph publication's configuration.

## Reading Order

1. [Sharded-K4 hardware reconciliation](grasu_regraph_sharded_k4_hardware_reconcile_20260807.md):
   destination sharding, four frontends, and shared downstream resources.
2. [Native conversion](grasu_regraph_native_conversion_20260725.md) and
   [native E2E integration](grasu_regraph_native_e2e_20260725.md):
   the PMA-to-edge-stream interface and stage boundaries.
3. [K-pipeline freeze](grasu_regraph_k_pipeline_freeze_20260728.md):
   topology and scheduling assumptions for that implementation era.
4. [Physical HBM map](grasu_regraph_physical_hbm_map_20260728.md):
   logical resources versus physical memory binding.

## Algorithm and Capacity Details

- [Weighted dynamic SSSP](grasu_regraph_weighted_dynamic_sssp_20260725.md)
- [Residual PageRank](grasu_regraph_residual_pagerank_20260725.md)
- [Full PageRank](grasu_regraph_full_pagerank_20260725.md)
- [Algorithm capabilities](grasu_regraph_algorithm_capabilities_20260726.md)
- [Destination-19 partition fix](grasu_weighted_dst19_partition_fix_20260729.md)
- [HBM capacity preflight](grasu_regraph_hbm_capacity_preflight_20260730.md)

Hardware/model calibration records are in the
[calibration section](../../experiments/calibration/README.md). Matching this
port is a different question from reproducing original-publication G or R
performance; no directory move establishes that equivalence.

## Code Review

The [original GraSU source-path control](original_grasu_source_path.md) checks
search, BIPA, dispatch, both URAM-cache/DDR halves and every state slot through
unmodified source functions. It is separate from the production direct-cache
port and does not yet model finite timing or original host preparation.
The separate [original GraSU host control](original_grasu_host.md) adds original
trace-aware reservation and merge, with two explicit bounds guards and defined
upload padding. Empty/full occupancy, repeated updates and the cache threshold
pass; finite timing and publication throughput remain unadmitted.
The [isolated original GraSU DDR RTL control](original_grasu_ddr_rtl.md)
checks aliased physical memory, finite queues, repeated-segment ordering and
complete state against the original source. It constrains one G component;
complete G finite timing, cache/search timing and publication matching remain open.
The separate [finite G composition owner](original_grasu_finite.md) connects
search, cache and DDR through shared physical banks, bounded queues and
complete state/traffic gates. Its timing is a declared prediction, not a
replacement for the original RTL or publication-admission controls.

The [independent original-ReGraph Little core](original_regraph_little_gather.md)
has a separate implementation and explicit partial timing boundary. It is a
publication-control building block, not a replacement for the ported G+R model.
The [Little input-path extension](original_regraph_little_frontend.md) owns
edge AXI reads, request-dependent source-memory service and Scatter separately;
it stops before Apply/writeback and retains predicted, not measured, timing.
The [Little PR state extension](original_regraph_little_state.md) adds separately
owned indexer, degree/Apply and acknowledged broadcast writer components, plus
a connected resident-round fixture. Its timing is still predicted, and it does
not establish Big/mixed or publication-performance equivalence.
The [original-host input owner](original_regraph_inputs.md) executes pinned
DBG/partition/scheduling and PR initialization with full graph/capture checks;
it supplies whole-path inputs but does not model device timing.
The [A4 whole-graph execution owner](original_regraph_a4_execution.md) connects
all admitted partitions through four state replicas, with nonintrusive
pre-Apply validation, explicit AXI capacities and exact old-default regression.
Its finite mock-memory cycles remain predictions, not publication matching.
The optional [weighted-SSSP four-Little control](../../experiments/comparisons/grasu_regraph_stage_validation/actual_sharded_k4/matched_a4/sssp_control/README.md)
adds a local UDF and separately owned finite old-state Apply. It checks
complete one-round A4/K4 states and exact PR regression; SSSP HLS timing,
matched resources and performance admission remain separate gates.
The subsequent [real-topology SSSP round](../../experiments/comparisons/grasu_regraph_stage_validation/actual_sharded_k4/matched_a4/sssp_real_round/README.md)
preserves the author's DBG/tasks and uses a locally synthesized post-response
Apply schedule. Complete states and traffic pass under both declared memory
latencies. Single-partition mock-memory timing is diagnostic, not an A4 FPGA
calibration, multi-round convergence result, or equal-resource overhead claim.
The [PMA adapter input control](original_regraph_adapter_source.md) preserves
the A4 task multiset, checks existing HLS packets and extracts shared wiring
with exact regression. That source checkpoint does not establish finite B
timing or overhead.
The [finite PMA/A4 control](finite_pma_original_a4.md) now has a separate
registered reader, shared original downstream, source-packet routing controls,
and matched input credits. Its experiment reports distinguish predicted
overhead from FPGA calibration and original-publication performance.
The [independent Big routing/Gather owner](original_regraph_big_gather.md)
models the original three-layer omega network and eight partitioned banks,
separately from Little. Its finite component/source/reuse gates do not yet
include Big source-memory service or complete mixed-system timing.
The [Big memory/Scatter owner](original_regraph_big_frontend.md) separately
adds request batches, the last-cacheline wrapper, initial/lane routing and
source-property Scatter. That checkpoint stops before mixed-system integration.

The [mixed whole-graph owner](original_regraph_mixed_execution.md) connects
that path to Little, independent write-index arbitration, Apply and 14 state
replicas. Original publication-tail allocation differences are rejected and
explicitly controlled, not silently clipped. Its complete-state regression
does not by itself establish publication timing.

Start with the [C++ ownership map](../../../cpp/README.md). Runtime HBM
placement and destination-shard update sequencing now have separate source
files behind the existing public header. The
[extraction record](../../repository/grasu_component_refactor/README.md)
documents the fixed regression matrix; readers, compute, and round control
previously shared a larger implementation file. The subsequent
[actual-K4 model checkpoint](../../experiments/comparisons/grasu_regraph_stage_validation/actual_sharded_k4/model_sync/README.md)
extracts the legacy PMA reader and validates a separately owned raw AXIS
adapter. The subsequent [compute/port checkpoint](../../experiments/comparisons/grasu_regraph_stage_validation/actual_sharded_k4/model_sync/compute_ports/README.md)
extracts Gather, merger, Apply and source-state writing and connects their
arithmetic to finite shared-port clients in tests. Source service, per-kernel
dispatch and whole-round backend composition still need further work; the
new topology is not yet selected by a production profile.
The [complete SSSP candidate composition](../../experiments/comparisons/grasu_regraph_stage_validation/actual_sharded_k4/model_sync/system/README.md)
now connects those components, with independent dispatch, one whole-round
backend and complete state/traffic checks. It targets the measured four-master
SSSP wrapper, not the later pairwise HLS source. SST selection and hardware
timing admission remain separate open gates.
