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
| Spine maintenance and carry | [spine_l0.hpp](include/spine_sim/spine_l0.hpp) | [spine_l0.cpp](src/spine_l0.cpp) |
| Spine dirty frontier and owner scheduling | [spine_dirty.hpp](include/spine_sim/spine_dirty.hpp), [spine_owner.hpp](include/spine_sim/spine_owner.hpp) | [spine_dirty.cpp](src/spine_dirty.cpp), [spine_owner.cpp](src/spine_owner.cpp) |
| Spine range resolution and edge/value stream reading | [spine_split.hpp](include/spine_sim/spine_split.hpp) | [spine_split.cpp](src/spine_split.cpp) |
| Spine SSSP/CC state update and owner publication | [spine_split.hpp](include/spine_sim/spine_split.hpp) | [spine_sssp_compute.cpp](src/spine_sssp_compute.cpp) |
| Spine system/algorithm orchestration | [spine_system.hpp](include/spine_sim/spine_system.hpp) | [spine_system.cpp](src/spine_system.cpp), [spine_pagerank.cpp](src/spine_pagerank.cpp) |
| GraSU PMA layout and update paths | [grasu.hpp](include/spine_sim/grasu.hpp), [grasu_native.hpp](include/spine_sim/grasu_native.hpp) | [grasu.cpp](src/grasu.cpp), [grasu_native.cpp](src/grasu_native.cpp) |
| G+R HBM buffer placement and capacity checks | [grasu_regraph.hpp](include/spine_sim/grasu_regraph.hpp) | [grasu_regraph_runtime.cpp](src/grasu_regraph_runtime.cpp) |
| G+R destination-shard update sequencing | [grasu_regraph.hpp](include/spine_sim/grasu_regraph.hpp) | [grasu_sharded_update.cpp](src/grasu_sharded_update.cpp) |
| G+R readers, compute, and iteration control | [grasu_regraph.hpp](include/spine_sim/grasu_regraph.hpp) | [grasu_regraph.cpp](src/grasu_regraph.cpp) |
| Independent original-ReGraph Little path, PR state and separate Big omega/banks/merge | [original_regraph/](include/spine_sim/original_regraph/) | [original_regraph/](src/original_regraph/) |
| SST setup and run serialization | SST component registration | [online_memory_probe.cpp](sst/online_memory_probe.cpp) |
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
| Owner/reactivation protocol | [spine_owner_tests.cpp](tests/spine_owner_tests.cpp) |
| Vertex lifecycle | [spine_vertex_lifecycle_tests.cpp](tests/spine_vertex_lifecycle_tests.cpp) |
| SST address mapping without an SST installation | [sst_hbm_mapper_tests.cpp](tests/sst_hbm_mapper_tests.cpp) |
| Independent author-source G/R controls | [publication_sources/](tests/publication_sources/) via [study runner](../scripts/run_upstream_stage_controls.py) |
| Independent original-R finite Gather/merge | [original_regraph/](tests/original_regraph/) via [validation runner](../scripts/run_original_regraph_gather_validation.py) |
| Independent original-R memory/frontend | [frontend_tests.cpp](tests/original_regraph/frontend_tests.cpp) via [frontend validation](../scripts/run_original_regraph_frontend_validation.py) |
| Independent original-R PR state and resident rounds | [state_tests.cpp](tests/original_regraph/state_tests.cpp), [iteration_tests.cpp](tests/original_regraph/iteration_tests.cpp) via [state validation](../scripts/run_original_regraph_state_validation.py) |
| Original-host graph/DBG/partition/task preparation | [regraph_layout_probe.cpp](tests/publication_sources/regraph_layout_probe.cpp) via [input runner](../scripts/run_original_regraph_inputs.py); no device timing |
| Independent original-A4 full graph execution | [whole_graph/](tests/original_regraph/whole_graph/) via [A4 runner](../scripts/run_original_regraph_a4.py); finite model timing, not FPGA/publication matching |
| Independent original-R Big omega/banks/merger | [big_tests.cpp](tests/original_regraph/big_tests.cpp), [big_comparison.cpp](tests/original_regraph/big_comparison.cpp) via [Big runner](../scripts/run_original_regraph_big_validation.py); partial predicted timing |
| Independent original-R Big memory/Scatter | [big_frontend_tests.cpp](tests/original_regraph/big_frontend_tests.cpp), [big_frontend_comparison.cpp](tests/original_regraph/big_frontend_comparison.cpp) via [Big frontend runner](../scripts/run_original_regraph_big_frontend_validation.py); separate cache/request/read ledgers |
| Independent original-R 11+3 whole graph | [mixed/](tests/original_regraph/whole_graph/mixed/) via [mixed runner](../scripts/run_original_regraph_mixed.py); complete indexed state and explicit publication-tail padding, not publication timing |
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

The first C++ extraction separates two existing responsibilities without
changing their public header or function bodies:

1. Runtime placement consumes a partitioned PMA layout and update counts;
   it returns deterministic buffer regions or rejects invalid/capacity-limited
   geometry. It does not issue simulated memory requests.
2. Sharded update orchestration consumes that placement and the update batch;
   it launches the existing native update engine one destination shard at a
   time, preserves degree initialization, and combines counters.
3. Readers, source service, gather/merge/apply, and round control remain in
   `grasu_regraph.cpp`. Their next extraction must preserve registration
   order, FIFO ownership, and shared-downstream backpressure.

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
