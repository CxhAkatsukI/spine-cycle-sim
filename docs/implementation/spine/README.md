# Spine Implementation

## Read First

1. [Device owner scheduler](spine_device_owner_scheduler_20260803.md):
   per-key ownership, reactivation, and completion.
2. [Four-algorithm owner alignment](spine_four_algorithm_owner_alignment_20260803.md):
   how the policy systems share that protocol.
3. [Device-active E2E correction](device_timed_active_e2e_20260801.md):
   the host-active timing problem and its device-modeled replacement.
4. [Device source directory and spool](device_source_directory_spool_20260803.md):
   bounded reader/source preparation.
5. [Device residual correction](spine_device_residual_correction_20260801.md):
   PageRank correction and seed work.
6. [Vertex lifecycle](spine_vertex_lifecycle_system_20260803.md):
   activation and deactivation scope.

## Component Details

- Maintenance: [L0 writer](spine_online_l0_writer_20260724.md),
  [carry writer](spine_online_carry_writer_20260724.md), and
  [exact maintenance result](spine_exact_maintenance_result_20260724.md).
- Reader/compute: [range-task reader](spine_exact_range_task_reader_20260724.md),
  [edge payload path](spine_graph_edge_payload_path_20260724.md), and
  [compute AXI overlap](spine_compute_loop_axi_overlap_20260724.md).
- Algorithm execution: [SSSP rounds](spine_multiround_sssp_20260723.md),
  [residual PageRank](spine_timed_residual_pagerank_20260725.md), and
  [Full PageRank](spine_timed_full_pagerank_compute_20260725.md).
- Reader optimizations: [opt-v1](spine_opt_v1_fallback_level_cache_20260728.md)
  and [opt-v2](spine_opt_v2_reader_working_set_20260728.md).

Other files in this directory document individual implementation steps. Keep
their original profile and timing scope when using them. Host-active records
describe a historical path, not permission to omit device work from a new test.
See the [full record catalog](../../repository/document_catalog.md) for lookup.
