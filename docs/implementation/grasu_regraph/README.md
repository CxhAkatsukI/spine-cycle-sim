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

The [independent original-ReGraph Little core](original_regraph_little_gather.md)
has a separate implementation and explicit partial timing boundary. It is a
publication-control building block, not a replacement for the ported G+R model.
The [Little input-path extension](original_regraph_little_frontend.md) owns
edge AXI reads, request-dependent source-memory service and Scatter separately;
it stops before Apply/writeback and retains predicted, not measured, timing.

Start with the [C++ ownership map](../../../cpp/README.md). Runtime HBM
placement and destination-shard update sequencing now have separate source
files behind the existing public header. The
[extraction record](../../repository/grasu_component_refactor/README.md)
documents the fixed regression matrix; readers, compute, and round control
still share a larger implementation file.
