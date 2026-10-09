# Runtime and Memory Integration

## Read First

- [SST online-memory backend](sst_online_memory_backend_20260723.md):
  how finite-resource execution reaches the memory backend.
- [Dynamic SSSP integration](sst_spine_dynamic_sssp_20260725.md),
  [residual PageRank integration](sst_spine_residual_pagerank_20260725.md),
  and [Full PageRank integration](sst_spine_full_pagerank_20260725.md).
- [Exact DRAMSim3 idle advancement](dramsim3_exact_idle_advance_20260727.md):
  an optimization with a memory-clock equivalence requirement.
- [Dynamic AXI sleep](scheduler_dynamic_axi_sleep_20260727.md) and
  [phase dispatch](scheduler_phase_dispatch_20260727.md):
  scheduling behavior and wakeup conditions.

[Runtime profiling](runtime_hotpath_profile_20260727.md) and
[rejected paths](runtime_rejected_paths_20260727.md) record their original
investigations. The larger tuning series is separated into
[runtime optimization history](../../history/runtime_optimization/README.md).

Use the [code map](../../../cpp/README.md) for build boundaries. Simulator
wall-clock optimization must preserve modeled cycles and request ledgers; it
does not establish hardware timing calibration.
