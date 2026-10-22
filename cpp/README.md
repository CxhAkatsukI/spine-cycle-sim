# C++ Code Map

The core in `include/spine_sim/` and `src/` implements cycle-level execution.
The SST plugin in `sst/` connects that engine to SST and the memory backend.
The Python layer prepares and checks runs; it is not the current C++ engine.

## Review Order

1. Read [component.hpp](include/spine_sim/component.hpp),
   [fifo.hpp](include/spine_sim/fifo.hpp), and
   [scheduler.cpp](src/scheduler.cpp) for execution phases and backpressure.
2. Read [memory_backend.cpp](src/memory_backend.cpp) and [axi.cpp](src/axi.cpp)
   for memory service and request/response accounting.
3. Read the affected architecture's public header before its implementation.
4. Inspect the selected profile, runner, and oracle checks together.
5. Check the SST wiring and output fields touched by the change.

## Component Ownership

| Responsibility | Public contract | Implementation |
| --- | --- | --- |
| Algorithm arithmetic and finite compute pipeline | [algorithm.hpp](include/spine_sim/algorithm.hpp), [algorithm_pipeline.hpp](include/spine_sim/algorithm_pipeline.hpp) | [algorithm.cpp](src/algorithm.cpp), [algorithm_pipeline.cpp](src/algorithm_pipeline.cpp) |
| AXI and memory service | [axi.hpp](include/spine_sim/axi.hpp), [memory_backend.hpp](include/spine_sim/memory_backend.hpp) | [axi.cpp](src/axi.cpp), [memory_backend.cpp](src/memory_backend.cpp) |
| Explicit independent read/write channels | [version-2 profile](../configs/architectures/grasu_regraph_routed_sssp_compute_v2.json) | [axi_independent_channels.cpp](src/axi_independent_channels.cpp), [response selection](src/detail/backend_response_selection.hpp); default-off, one physical initiator and unchanged issue bandwidth |
| Routed profile selection | [selection contract](include/spine_sim/routed_regraph_profile.hpp) | [profile factory](src/routed_regraph/profile.cpp); rejects mixed modes, preserves legacy defaults and explicitly selects the [source-bound bank-stream candidate](../docs/experiments/comparisons/grasu_regraph_stage_validation/actual_sharded_k4/model_sync/system/bank_stream/README.md), not hardware timing admission |
| Spine maintenance and carry | [spine_l0.hpp](include/spine_sim/spine_l0.hpp) | [spine_l0.cpp](src/spine_l0.cpp) |
| Spine dirty frontier and owner scheduling | [spine_dirty.hpp](include/spine_sim/spine_dirty.hpp), [spine_owner.hpp](include/spine_sim/spine_owner.hpp) | [spine_dirty.cpp](src/spine_dirty.cpp), [spine_owner.cpp](src/spine_owner.cpp) |
| Spine range resolution and edge/value stream reading | [spine_split.hpp](include/spine_sim/spine_split.hpp) | [spine_split.cpp](src/spine_split.cpp) |
| Spine SSSP/CC state update and owner publication | [spine_split.hpp](include/spine_sim/spine_split.hpp) | [spine_sssp_compute.cpp](src/spine_sssp_compute.cpp) |
| Spine system/algorithm orchestration | [spine_system.hpp](include/spine_sim/spine_system.hpp) | [spine_system.cpp](src/spine_system.cpp), [spine_pagerank.cpp](src/spine_pagerank.cpp) |
| GraSU PMA layout and update paths | [grasu.hpp](include/spine_sim/grasu.hpp), [grasu_native.hpp](include/spine_sim/grasu_native.hpp) | [grasu.cpp](src/grasu.cpp), [grasu_native.cpp](src/grasu_native.cpp) |
| Read-only G progress and port observations | `GraSuPmaUpdateSystem::progress`, `port_observations` | Optional [common-G sampler](tests/evaluation_impact/common_g/diagnostics.hpp); [exact-replay scope](../docs/experiments/comparisons/grasu_regraph_stage_validation/evaluation_impact/search_diagnostics/README.md), no scheduler change or FPGA counters |
| Experimental finite parallel G search | [search interface](include/spine_sim/grasu_update/search.hpp) | [parallel search](src/grasu_update/parallel_search.cpp); explicit default-off 16/64-context single-window controls, [concurrency and resource limits](../docs/experiments/comparisons/grasu_regraph_stage_validation/evaluation_impact/search_concurrency/README.md), not production or FPGA timing admission |
| Experimental registered 8x8 G search | [finite search wiring](src/grasu_update/finite_search.cpp), [worker/transport owner](src/grasu_update/finite_search/) | Default-off 339-channel HLS counterpart, [schedule assumptions and required evidence](../docs/experiments/comparisons/grasu_regraph_stage_validation/evaluation_impact/search_pipeline/finite_model/README.md); no hardware timing or production admission |
| Experimental G metadata buffering | `GraSuNativeConfig::compact_metadata_credits` | Explicit default-zero 16/32/64-slot override on parallel-search row masters only; [complete control and resource scope](../docs/experiments/comparisons/grasu_regraph_stage_validation/evaluation_impact/metadata_credits/README.md), unchanged banks and default paths, not routed HLS |
| Direct G hot/cold segment RMW | [processor contract](include/spine_sim/grasu_update/processor.hpp), [pure PMA helpers](include/spine_sim/grasu_update/pma_word.hpp) | [direct processor](src/grasu_update/direct_processor.cpp); extracted default topology plus explicit segment-ordered hot-owner candidate, [full-matrix limits](../docs/experiments/comparisons/grasu_regraph_stage_validation/evaluation_impact/hot_lanes/README.md), no implicit cache or production promotion |
| Experimental full-depth G hot cache | [cache contract](include/spine_sim/grasu_update/cached_processor.hpp) | [cached processor](src/grasu_update/cached_processor.cpp); default-off preload, finite banks/forwarding and acknowledged writeback, [scope and open gates](../docs/experiments/comparisons/grasu_regraph_stage_validation/evaluation_impact/cached_hot/README.md), not routed G or FPGA timing |
| G+R HBM buffer placement and capacity checks | [grasu_regraph.hpp](include/spine_sim/grasu_regraph.hpp) | [grasu_regraph_runtime.cpp](src/grasu_regraph_runtime.cpp) |
| G+R destination-shard update sequencing | [grasu_regraph.hpp](include/spine_sim/grasu_regraph.hpp) | [grasu_sharded_update.cpp](src/grasu_sharded_update.cpp) |
| Prepared-shard G batch control | [test owners](tests/evaluation_impact/common_g/sharded/), [synthetic scope](../docs/experiments/comparisons/grasu_regraph_stage_validation/evaluation_impact/sharded_batch/README.md), [compact real-input extension](../docs/experiments/comparisons/grasu_regraph_stage_validation/evaluation_impact/sharded_batch/real_inputs/README.md) | Separate fixtures/oracles and thin CLIs reuse original/candidate execution; complete physical buffers and cache/search traffic, predicted timing only |
| Resident G metadata-copy control | [replica allocation](tests/evaluation_impact/common_g/sharded/metadata_layout/replicas.hpp), [fixture/residency/execution owners](tests/evaluation_impact/common_g/sharded/metadata_layout/lifecycle/), [scope and evidence](../docs/experiments/comparisons/grasu_regraph_stage_validation/evaluation_impact/sharded_batch/metadata_layout/lifecycle/README.md) | Consecutive fixed-reservation batches, persistent backend, physical copy/padding checks and exact prior replay; no production/HLS binding change or host-inclusive timing |
| Resident chronological G extension | [real-input fixture and wrapper checks](tests/evaluation_impact/common_g/sharded/metadata_layout/resident_real/), [declared matrix and evidence](../docs/experiments/comparisons/grasu_regraph_stage_validation/evaluation_impact/sharded_batch/metadata_layout/resident_real/README.md) | Reuses lifecycle batch oracles, allocation and execution; checks consecutive AU/SU/WK batches on two/three bounded shards and distinguishes fixed-resident from per-batch allocation geometry. No production numerical source or SST change |
| Resident G-to-R physical handoff | Default-off `reuse_resident_pma` in [routed_regraph.hpp](include/spine_sim/routed_regraph.hpp) | [Payload validation](src/routed_regraph/resident_memory.cpp), [small correctness/rejection matrix](tests/evaluation_impact/handoff/), [direct checkpoint](../docs/experiments/comparisons/grasu_regraph_stage_validation/evaluation_impact/composition/README.md), [finite bank routing](../docs/experiments/comparisons/grasu_regraph_stage_validation/evaluation_impact/composition/banked/README.md), [full-cache sharded controls](../docs/experiments/comparisons/grasu_regraph_stage_validation/evaluation_impact/composition/cached/README.md); no graph rebuild, sharded performance still open |
| G+R legacy PMA reader | [private stream contract](src/detail/grasu_regraph_streams.hpp) | [grasu_regraph_legacy_reader.cpp](src/grasu_regraph_legacy_reader.cpp) |
| G+R legacy source service, composition and iteration control | [grasu_regraph.hpp](include/spine_sim/grasu_regraph.hpp) | [grasu_regraph.cpp](src/grasu_regraph.cpp) |
| G+R Gather, merger, Apply and source-state writer | [private compute contract](src/detail/grasu_regraph_compute.hpp) | [gather](src/grasu_regraph_gather.cpp), [merger](src/grasu_regraph_merger.cpp), [apply](src/grasu_regraph_apply.cpp), [writeback](src/grasu_regraph_writeback.cpp) |
| Shared physical AXI clients | [queue view](include/spine_sim/axi_endpoint.hpp), [finite mux](include/spine_sim/shared_axi_port.hpp) | [shared_axi_port.cpp](src/shared_axi_port.cpp); selected only by the explicit routed compute candidate, not legacy v8 |
| Routed shared-master PMA adapter | [regraph_pma_adapter.hpp](include/spine_sim/regraph_pma_adapter.hpp) | [regraph_pma_adapter.cpp](src/regraph_pma_adapter.cpp); explicit candidate selection, legacy defaults unchanged |
| Routed raw-packet Scatter and source-block service | [Scatter contract](src/detail/routed_regraph_scatter.hpp), [source contract](src/detail/routed_regraph_source.hpp) | [scatter](src/routed_regraph/scatter.cpp), [source service](src/routed_regraph/source_service.cpp); measured SSSP uses dedicated readers, later worktree uses pairwise readers |
| Complete measured-topology SSSP candidate | [routed_regraph.hpp](include/spine_sim/routed_regraph.hpp) | [routed_regraph/](src/routed_regraph/); separate admission, serialization, composition, transport and round owners |
| Routed inter-kernel FIFO capacities | [version-3 profile](../configs/architectures/grasu_regraph_routed_sssp_compute_v3.json) | Three explicit depth fields in the system contract; [composition](src/routed_regraph/composition.cpp) preserves v1/v2 defaults, and [the structural audit](../spine_cycle_sim/experiments/sharded_k4_stages/stream_contract.py) checks 19 routed connections |
| Routed empty-row exit | [version-4 profile](../configs/architectures/grasu_regraph_routed_sssp_compute_v4.json) | An explicit adapter wait for visited empty rows, grounded in [generated-RTL tests](../docs/experiments/comparisons/grasu_regraph_stage_validation/actual_sharded_k4/model_sync/sst/empty_row_rtl/README.md); zero preserves earlier timing, skipped rows remain free |
| Unrouted whole-line directory candidate | [explicit model profile](../configs/architectures/grasu_regraph_row_line_sssp_compute_v1.json) | Default-off `row_line_reads` in the actual PMA adapter; eight valid entries per aligned response, a separate extent read, unchanged finite resources and legacy timing. This is not the independent PMA+A4 reader or a new measured bitstream. |
| Unrouted cross-row pipeline candidate | [explicit profile](../configs/architectures/grasu_regraph_cross_row_sssp_compute_v1.json) | [reader](src/regraph_pma_cross_row/reader.cpp), [publisher](src/regraph_pma_cross_row/publisher.cpp), [control](src/regraph_pma_cross_row/control.cpp) and private [state](src/regraph_pma_cross_row/state.hpp); finite shared AXI/FIFO overlap, default-off, exact legacy replay. [Evidence and limits](../docs/experiments/comparisons/grasu_regraph_stage_validation/actual_sharded_k4/adapter_optimization/row_line/cross_row/model/README.md) distinguish structural prediction from FPGA timing. |
| Unrouted tiled-directory and bank-stream candidates | Explicit `cross_row` schedule in [regraph_pma_adapter.hpp](include/spine_sim/regraph_pma_adapter.hpp) | [Directory cache](src/regraph_pma_cross_row/directory_tile.cpp), [bank issue](src/regraph_pma_cross_row/bank_loader.cpp), [progressive returns](src/regraph_pma_cross_row/bank_returns.cpp), [ordered join](src/regraph_pma_cross_row/bank_join.cpp) and [packet publication](src/regraph_pma_cross_row/packet_pipeline.cpp); finite 128/256-line bank storage, legacy defaults preserved. [Fixed A4 control and limits](../docs/experiments/comparisons/grasu_regraph_stage_validation/actual_sharded_k4/adapter_optimization/row_line/directory_tile/README.md) admit prediction only, not FPGA timing. |
| HLS-exported resident input | [routed_regraph_fixture.hpp](include/spine_sim/routed_regraph_fixture.hpp) | [fixture loader](src/routed_regraph/fixture.cpp), [owning-HLS exporter](tools/routed_regraph/export_hls_fixture.cpp); preserves reserved slots and update result |
| Shared-port completion diagnostic | [isolated driver](tools/routed_regraph/diagnose_stream_write.cpp) | [capped state and controls](../docs/experiments/comparisons/grasu_regraph_stage_validation/actual_sharded_k4/model_sync/sst/completion_diagnostic/README.md); reproduces current read/write blocking, not a model fix or FPGA calibration |
| Independent original-ReGraph Little path, PR state and separate Big omega/banks/merge | [original_regraph/](include/spine_sim/original_regraph/) | [original_regraph/](src/original_regraph/) |
| Independent finite PMA input for matched original A4 | [pma_adapter/](include/spine_sim/pma_adapter/) | [reader.cpp](src/pma_adapter/reader.cpp); separate library, not production SST |
| Experimental finite prefetch/compaction R input | [resource and ownership contract](tests/evaluation_impact/prefetch_compact/README.md) | Reusable reader/request/join/compactor owners in `src/detail/prefetch_compact/`, composed by [input.cpp](src/routed_regraph/input.cpp); separate diagnostic sinks and [complete-convergence evidence](../docs/experiments/comparisons/grasu_regraph_stage_validation/evaluation_impact/r_bank_stream/prefetch_compact/CONVERGENCE.md). Default-off; correctness passes, performance retention does not |
| Passive R wait observations | [typed snapshot](include/spine_sim/routed_regraph_observation.hpp), [definitions and gates](../docs/experiments/comparisons/grasu_regraph_stage_validation/evaluation_impact/r_bank_stream/prefetch_compact/OBSERVATIONS.md) | [Snapshot accessor](src/routed_regraph/system.cpp), [pre-edge Apply observer](src/detail/routed_regraph_observer.hpp), [CSV export](tests/evaluation_impact/wait_observations.hpp); separate overlapping observations, not exclusive phase times or FPGA counters |
| Independent original-G search/cache/DDR composition | [original_grasu/](include/spine_sim/original_grasu/) | [original_grasu/](src/original_grasu/); shared four-bank control, separate library, not production SST |
| SST setup and run serialization | SST component registration | [online_memory_probe.cpp](sst/online_memory_probe.cpp) |
| Explicit routed SSSP SST candidate | [version-1 profile](../configs/architectures/grasu_regraph_routed_sssp_compute_v1.json) | [probe](sst/routed_regraph_probe.cpp), [report](sst/routed_regraph_report.cpp); separate component, no legacy probe branch |
| SST physical HBM address mapping | [physical_hbm_mapper.hpp](sst/physical_hbm_mapper.hpp) | [physical_hbm_mapper.cpp](sst/physical_hbm_mapper.cpp) |
| SST memory reservation, transport and completion | [sst_memory_backend.hpp](sst/sst_memory_backend.hpp) | [sst_memory_backend.cpp](sst/sst_memory_backend.cpp) |
| Direct DRAMSim3 bridge | [direct_dramsim3_engine.hpp](sst/direct_dramsim3_engine.hpp) | [direct_dramsim3_engine.cpp](sst/direct_dramsim3_engine.cpp) |

## Two Build Entry Points

- [CMakeLists.txt](CMakeLists.txt) builds the core library, host benchmark, and
  C++ tests. It does not build the SST plugin.
- [sst/Makefile](sst/Makefile) builds `libspine_cycle.so` from its own source
  list, SST configuration, compiler flags, and optional DRAMSim3 linkage.

A source-file split must update both applicable build lists. A passing CMake
test alone does not establish that the SST plugin contains the change.
Use a new `BUILD_DIR` when checking plugin changes; preserve frozen libraries
used by existing experiments.

## Test Layers

| Layer | Entry |
| --- | --- |
| Shared core and Spine execution | [core_tests.cpp](tests/core_tests.cpp) |
| GraSU and G+R execution | [grasu_tests.cpp](tests/grasu_tests.cpp) |
| G+R placement, capacity, and empty-shard invariants | [grasu_runtime_tests.cpp](tests/grasu_runtime_tests.cpp) |
| Routed adapter packet, pressure, completion and optional production-HLS checks | [routed_regraph/](tests/routed_regraph/) via [model runner](../scripts/validate_sharded_k4_adapter_model.py) |
| Cross-row logical RTL-shape diagnostic | [adapter_timing_matrix.hpp](tests/routed_regraph/adapter_timing_matrix.hpp) via `routed_pma_adapter_tests --rtl-matrix`; all twelve shapes/two arms retained, not identical endpoints or calibrated HBM timing |
| Shared resident K4 round-test composition | [round_execution.hpp](tests/routed_regraph/round_execution.hpp), with thin [legacy](tests/routed_regraph/empty_segment/round.cpp), [whole-line](tests/routed_regraph/row_line/round.cpp) and [cross-row](tests/routed_regraph/cross_row/round.cpp) CLIs; exact historical reference cycles/counters/full states, candidate traffic conservation, not a production topology change |
| Passive production adapter observation | [occupied_row_monitor.sv](tests/routed_regraph/occupied_row_monitor.sv); read-only helper/packet events beside the unchanged AXI bench, with [complete raw replay](../docs/experiments/comparisons/grasu_regraph_stage_validation/actual_sharded_k4/adapter_optimization/row_line/occupied_rows/README.md), not FPGA stage calibration |
| Independent-channel pressure and legacy behavior | [axi/](tests/axi/); paused read consumer, independent R/B/W stalls, finite credits, complete payload and registration-order checks |
| Owner/reactivation protocol | [spine_owner_tests.cpp](tests/spine_owner_tests.cpp) |
| Vertex lifecycle | [spine_vertex_lifecycle_tests.cpp](tests/spine_vertex_lifecycle_tests.cpp) |
| SST address mapping without an SST installation | [sst_hbm_mapper_tests.cpp](tests/sst_hbm_mapper_tests.cpp) |
| Independent author-source G/R controls | [publication_sources/](tests/publication_sources/) via [study runner](../scripts/run_upstream_stage_controls.py) |
| Original G search/cache/DDR functional composition | [grasu_path/](tests/publication_sources/grasu_path/) via [G source runner](../scripts/run_original_grasu_source_path.py); prepared PMA, not finite timing or original host validation |
| Original G host/kernel/merge composition | [grasu_host/](tests/publication_sources/grasu_host/) via [host control runner](../scripts/run_original_grasu_host.py); two declared bounds guards and defined padding, not finite timing |
| Original G DDR shared-memory RTL control | [grasu_ddr_rtl/](tests/grasu_ddr_rtl/) via [RTL control runner](../scripts/run_original_grasu_ddr_rtl.py); independent AXI bus tests and complete source/RTL state, not board or complete G timing |
| Original G finite shared-bank composition | [original_grasu/](tests/original_grasu/) via [finite G runner](../scripts/run_original_grasu_finite.py); all buffers, source requests and finite ledgers, with explicitly predicted timing |
| Original and candidate full-depth G hot-cache HLS/RTL | [cache controls](tests/evaluation_impact/common_g/hls/cache_bank.cpp), [complete cache wrapper](tests/evaluation_impact/common_g/hls/cache_full.cpp), [static edit wiring](tests/evaluation_impact/common_g/hls/cache_lane.hpp) via [probe package](../spine_cycle_sim/experiments/evaluation_impact/common_g/cache_probe/); optional Vitis controls, not core/SST or whole-G performance admission |
| Same-stimulus cache-service timing control | [cache_timing.cpp](tests/evaluation_impact/common_g/cache_timing.cpp), optional target `grasu_cache_timing_control`; six complete-state cases, finite AXI traffic and reverse-registration checks. [Analysis](../spine_cycle_sim/experiments/evaluation_impact/common_g/cache_probe/timing_analysis.py) compares service increments, not mock-memory total time against RTL or FPGA time. |
| Finite 64-context G search HLS candidate | [search stages and bounded host controls](tests/evaluation_impact/common_g/hls/search_pipeline/), [runner package](../spine_cycle_sim/experiments/evaluation_impact/common_g/search_pipeline/), [scope and evidence](../docs/experiments/comparisons/grasu_regraph_stage_validation/evaluation_impact/search_pipeline/README.md); ordered work and source backpressure checks, separate queued RTL/clock gates, not whole-G or core/SST timing admission |
| Weighted host/search/cache/adapter source compatibility | [weighted ABI control](tests/evaluation_impact/common_g/weighted_abi/), [runner package](../spine_cycle_sim/experiments/evaluation_impact/common_g/weighted_abi/), [scope and evidence](../docs/experiments/comparisons/grasu_regraph_stage_validation/evaluation_impact/weighted_abi/README.md); hot edits, complete intermediate state and actual adapter packets, not finite timing or whole-G admission |
| Native multi-shard G hot/cold source coverage | [fixture and control](tests/evaluation_impact/common_g/complete_pipeline/native_geometry/), [runner and delivery](../spine_cycle_sim/experiments/evaluation_impact/common_g/complete_pipeline/native_geometry/), [scope and portable evidence](../docs/experiments/comparisons/grasu_regraph_stage_validation/evaluation_impact/hardware_validation/complete_pipeline/native_geometry/README.md); full cache, native partitions and resident direct handoff, not RTL, XRT binding or hardware timing |
| Continuous G XRT host preflight | [model, device bindings and thin CLI](tests/evaluation_impact/common_g/continuous_board/), [runner package](../spine_cycle_sim/experiments/evaluation_impact/common_g/continuous_board/), [scope and evidence](../docs/experiments/comparisons/grasu_regraph_stage_validation/evaluation_impact/hardware_validation/complete_pipeline/continuous_board/README.md); eighteen host-only rows and exact 42-row source regression, compiled but unexecuted board path, not FPGA timing |
| Native five-shard G XRT extension | [model and thin CLI](tests/evaluation_impact/common_g/native_board/), [shared physical-state helpers](tests/evaluation_impact/common_g/continuous_board/resident_state.hpp), [shared batch execution](tests/evaluation_impact/common_g/continuous_board/execution.hpp), [scope and portable capsules](../docs/experiments/comparisons/grasu_regraph_stage_validation/evaluation_impact/hardware_validation/complete_pipeline/native_board/README.md); five native shards/full cache/hot+cold paths, fresh compilation, eighteen deterministic old host-model rows, three native host-model rows and six exact source-regression rows pass, no board timing |
| Same-input production G control | [input/model, leased execution and CLI](tests/evaluation_impact/common_g/matched_original/), [preflight owner](../spine_cycle_sim/experiments/evaluation_impact/common_g/matched_original/), [scope and reproduction](../docs/experiments/comparisons/grasu_regraph_stage_validation/evaluation_impact/hardware_validation/original_grasu/matched_production/README.md); preserves original logical slots/reservation/order, reuses actual production buffers/XRT, host replay is not original-G performance admission |
| Native resident metadata lifecycle | [remap fixture, device refresh and thin CLI](tests/evaluation_impact/common_g/metadata_refresh/), [runner/validation](../spine_cycle_sim/experiments/evaluation_impact/common_g/metadata_refresh/), [scope and queued attempt](../docs/experiments/comparisons/grasu_regraph_stage_validation/evaluation_impact/hardware_validation/complete_pipeline/metadata_refresh/README.md); two directory generations, same BOs, no PMA reset and stale-directory negative; thirteen Python tests pass, C++ preflight queued, device path unexecuted |
| Existing PMA adapter source and common A4 downstream | [adapter_probe.cpp](tests/publication_sources/adapter_probe.cpp) and [compute_wiring.hpp](tests/original_regraph/whole_graph/compute_wiring.hpp); source packets and exact A4 extraction checks, not finite B overhead |
| Finite PMA/A4 composition and original HLS routing | [pma_adapter/](tests/pma_adapter/), [adapter_routing_probe.cpp](tests/publication_sources/adapter_routing_probe.cpp) via [matched runner](../scripts/run_pma_regraph_control.py); complete state/traffic and predicted timing, not measured FPGA overhead |
| Independent original-R finite Gather/merge | [original_regraph/](tests/original_regraph/) via [validation runner](../scripts/run_original_regraph_gather_validation.py) |
| Independent original-R memory/frontend | [frontend_tests.cpp](tests/original_regraph/frontend_tests.cpp) via [frontend validation](../scripts/run_original_regraph_frontend_validation.py) |
| Independent original-R PR state and resident rounds | [state_tests.cpp](tests/original_regraph/state_tests.cpp), [iteration_tests.cpp](tests/original_regraph/iteration_tests.cpp) via [state validation](../scripts/run_original_regraph_state_validation.py) |
| Original-host graph/DBG/partition/task preparation | [regraph_layout_probe.cpp](tests/publication_sources/regraph_layout_probe.cpp) via [input runner](../scripts/run_original_regraph_inputs.py); no device timing |
| Independent original-A4 full graph execution | [whole_graph/](tests/original_regraph/whole_graph/) via [A4 runner](../scripts/run_original_regraph_a4.py); finite model timing, not FPGA/publication matching |
| Warm-convergence R credit controls | [control definitions](tests/evaluation_impact/control.hpp), [A4](tests/evaluation_impact/a4.hpp), [K4](tests/evaluation_impact/k4.hpp), [thin CLI](tests/evaluation_impact/convergence.cpp); [28-row scope and safety gates](../docs/experiments/comparisons/grasu_regraph_stage_validation/evaluation_impact/r_credits/README.md), not a strict resource match or admitted baseline |
| Independent original-R Big omega/banks/merger | [big_tests.cpp](tests/original_regraph/big_tests.cpp), [big_comparison.cpp](tests/original_regraph/big_comparison.cpp) via [Big runner](../scripts/run_original_regraph_big_validation.py); partial predicted timing |
| Independent original-R Big memory/Scatter | [big_frontend_tests.cpp](tests/original_regraph/big_frontend_tests.cpp), [big_frontend_comparison.cpp](tests/original_regraph/big_frontend_comparison.cpp) via [Big frontend runner](../scripts/run_original_regraph_big_frontend_validation.py); separate cache/request/read ledgers |
| Independent original-R 11+3 whole graph | [mixed/](tests/original_regraph/whole_graph/mixed/) via [mixed runner](../scripts/run_original_regraph_mixed.py); complete indexed state and explicit publication-tail padding, not publication timing |
| Original-R guarded XRT host control | [hardware/](tests/original_regraph/hardware/) via [offline validation](../spine_cycle_sim/experiments/original_regraph_execution/hardware/README.md); named divisor controls, full output/guard checks and event windows; compiled and offline-validated, not board-admitted |
| Original-G guarded XRT host control | [grasu_board/](tests/publication_sources/grasu_board/) separates independent PMA oracle, leased XRT runtime and nine-CU execution; [input replay and preflight](../docs/experiments/comparisons/grasu_regraph_stage_validation/evaluation_impact/hardware_validation/original_grasu/board_host/README.md) never programs a board |
| Python runner, profiles, and result gates | [tests/](../tests) |

Native GraSU/ReGraph result gates now have one Python owner:
[grasu_native_validation.py](../spine_cycle_sim/experiments/grasu_native_validation.py).
The legacy runner re-exports these functions for compatible CLI/import use.

The optional [author-source controls](../docs/experiments/comparisons/grasu_regraph_stage_validation/README.md)
compile pinned external GraSU/ReGraph sources, not local HLS ports or simulator
implementations. They require Vitis headers and GMP and are deliberately not
part of the dependency-free CMake core. Their functional acceptance does not
establish device timing or finite-buffer correctness.

The [HLS scheduling study](../docs/experiments/comparisons/grasu_regraph_stage_validation/HLS_SCHEDULES.md)
uses the same pinned author sources in isolated scratch projects. The small
`publication_sources/hls_portability.hpp` header supplies only the legacy
32-bit `uint` alias. No original algorithm body, production C++ component, or
SST build list is changed by that optional study. Its reports do not imply
that a complete independent original-G/ReGraph cycle model exists yet.

The [finite Little Gather/merge checkpoint](../docs/experiments/comparisons/grasu_regraph_stage_validation/LITTLE_FINITE_MODEL.md)
adds a separately owned CMake library with registered finite resources and
word-for-word author-source comparison. It stops before Apply and does not
include original edge/source memory service or Big scheduling. It is therefore
not wired into SST, and its predicted cycles are not whole-R throughput.

The [Little memory/frontend extension](../docs/implementation/grasu_regraph/original_regraph_little_frontend.md)
adds small separately owned edge-reader, source-service and Scatter modules,
with finite AXI memory paths and request-dependent original-source comparison.
Its fixed matrix preserves all accepted Gather/capture results and checks
registration order, backpressure, source-window gaps and allocation rejection.
Apply/writeback and complete original-R/adapter timing remain separate work;
this independent library is still not wired into the production SST plugin.

The [PR state extension](../docs/implementation/grasu_regraph/original_regraph_little_state.md)
owns degree/Apply, indexed writes and per-replica completion separately. Its
shared memory-test fixture preserves old frontend outputs exactly and permits
connected resident ping-pong iterations without host-generated next-state
properties. Source-word equivalence, finite-resource correctness and predicted
cycles remain distinct from whole-R publication or FPGA timing validation.

The [original-host input probe](../docs/implementation/grasu_regraph/original_regraph_inputs.md)
uses unmodified author loader/DBG/scheduler functions with small separate
mapping, full-edge validation and capture helpers. Its six-case matrix includes
complete Amazon for A4 and the artifact's 11+3 example. It is optional, needs
real OpenCL/XRT types, and does not add dependencies to the CMake core or SST.

The [whole-A4 validation executable](../docs/implementation/grasu_regraph/original_regraph_a4_execution.md)
separates binary input/reference checks, finite wiring/per-kernel task progress,
and nonintrusive full-state execution. It reuses the original numerical
components unchanged. An optional AXI parent-credit argument preserves every
old helper default while exposing single-line state-port concurrency.

## G+R Extraction Boundary

The optional [weighted-SSSP four-Little control](../docs/experiments/comparisons/grasu_regraph_stage_validation/actual_sharded_k4/matched_a4/sssp_control/README.md)
keeps arithmetic in [udf.hpp](include/spine_sim/original_regraph/udf.hpp) and
finite indexed old-state handling in [sssp_apply.cpp](src/original_regraph/sssp_apply.cpp).
Its [composed tests](tests/original_regraph/sssp/) check complete A4/K4
resident-round state, padding and replica acknowledgements. Existing
components default to PR. The external local-HLS UDF comparison is opt-in;
diagnostic cycles do not admit an original-publication or A4/K4 timing match.

The [real-topology resident-round extension](../docs/experiments/comparisons/grasu_regraph_stage_validation/actual_sharded_k4/matched_a4/sssp_real_round/README.md)
separates weighted capture decoding and the synchronous oracle in
[real_input.hpp](tests/original_regraph/sssp/real_input.hpp) from execution and
full replica/traffic checks in [real_round.cpp](tests/original_regraph/sssp/real_round.cpp).
Its explicit memory service and response-anchored SSSP Apply option leave
old PR defaults unchanged. One partition and differing publication/port
resources limit its cycle ratios to diagnostics.

The first C++ extraction separates two existing responsibilities without
changing their public header or function bodies:

1. Runtime placement consumes a partitioned PMA layout and update counts;
   it returns deterministic buffer regions or rejects invalid/capacity-limited
   geometry. It does not issue simulated memory requests.
2. Sharded update orchestration consumes that placement and the update batch;
   it launches the existing native update engine one destination shard at a
   time, preserves degree initialization, and combines counters.
3. The legacy combined PMA reader is separately owned. Gather, merger, Apply
   and the source-state writer now have separate implementations as well;
   source service, legacy composition and round control remain in
   `grasu_regraph.cpp`. The separate
   [adapter synchronization checkpoint](../docs/experiments/comparisons/grasu_regraph_stage_validation/actual_sharded_k4/model_sync/README.md)
   records a new full-result equivalence gate and a raw-adapter building block,
   not a completed candidate system or timing calibration.
4. The [compute/port checkpoint](../docs/experiments/comparisons/grasu_regraph_stage_validation/actual_sharded_k4/model_sync/compute_ports/README.md)
   preserves all five legacy results and tests finite shared-master clients
   with the extracted arithmetic. Actual per-kernel dispatch, source-block
   scheduling and one-round backend integration remain open.
5. The [frontend checkpoint](../docs/experiments/comparisons/grasu_regraph_stage_validation/actual_sharded_k4/model_sync/frontend/README.md)
   adds connected raw-packet Scatter/source gates and corrects the source
   topology identity: the measured SSSP XO has four source masters, whereas
   the current HLS worktree has two pairwise masters. These variants must not
   be substituted during calibration. Full-system wiring remains open.
6. The [complete SSSP candidate](../docs/experiments/comparisons/grasu_regraph_stage_validation/actual_sharded_k4/model_sync/system/README.md)
   subsequently connects independent frontend chains and the whole-round
   shared backend. Complete state, source replicas, scheduling and finite
   ledgers pass in bounded tests. The subsequent
   [SST diagnostic](../docs/experiments/comparisons/grasu_regraph_stage_validation/actual_sharded_k4/model_sync/sst/README.md)
   selects a distinct artifact-bound candidate and compares complete HLS-exported
   inputs with FPGA results. Matched FPGA timing remains unadmitted; the
   diagnostic preserves the nominal timing discrepancies instead of fitting them.
7. The [pairwise source checkpoint](../docs/experiments/comparisons/grasu_regraph_stage_validation/actual_sharded_k4/model_sync/system/source_pairs/README.md)
   owns the explicit two-service alternative in
   [source_topology.cpp](src/routed_regraph/source_topology.cpp). It preserves
   the earlier four-reader default and separately tests 0/2 and 1/3 sharing;
   neither core correctness nor a source-level topology match admits FPGA timing.

The [refactor record](../docs/repository/grasu_component_refactor/README.md)
contains the fixed pre/post SST matrix and full-result comparison. This is
incremental modularization, not completion of the entire C++ cleanup. The
[structure audit](../docs/repository/structure_audit_20261009.md) retains the
remaining SST and Spine extraction work.

## SST And Spine Extraction Boundary

The [SST/Spine regression record](../docs/repository/sst_spine_refactor/README.md)
tracks two independently checked checkpoints. `OnlineMemoryProbe` keeps SST
registration, run setup, algorithm references, and serialization; physical
address mapping and memory-backend arbitration/transport are separate units.
The backend still uses the original prepare/evaluate/commit order and shares
one completion/payload path between StandardMem and direct DRAMSim3.

`SpineSplitReader` remains in `spine_split.cpp` for source-path compatibility;
`SpineSplitSsspCompute` has its own implementation file. Their public header
is unchanged. The private [payload helper](src/detail/spine_split_payload.hpp)
contains only the existing shared encoders/decoders and ABI constants, not an
alternate scheduler or architecture. Owner scheduling remains in its existing
module. SST run setup/serialization and maintenance are still large and need
later, separately verified extractions.
