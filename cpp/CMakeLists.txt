add_library(spine_cycle_core STATIC
  src/algorithm.cpp
  src/algorithm_pipeline.cpp
  src/axi.cpp
  src/axi_independent_channels.cpp
  src/banked_memory.cpp
  src/grasu.cpp
  src/grasu_update/parallel_search.cpp
  src/grasu_update/finite_search.cpp
  src/grasu_update/finite_search/workers.cpp
  src/grasu_update/finite_search/transport.cpp
  src/grasu_update/direct_processor.cpp
  src/grasu_update/cached_processor.cpp
  src/grasu_native.cpp
  src/grasu_regraph.cpp
  src/grasu_regraph_gather.cpp
  src/grasu_regraph_merger.cpp
  src/grasu_regraph_apply.cpp
  src/grasu_regraph_writeback.cpp
  src/grasu_regraph_legacy_reader.cpp
  src/grasu_regraph_runtime.cpp
  src/grasu_sharded_update.cpp
  src/memory_backend.cpp
  src/regraph_pma_adapter.cpp
  src/regraph_pma_cross_row/reader.cpp
  src/regraph_pma_cross_row/directory_tile.cpp
  src/regraph_pma_cross_row/bank_loader.cpp
  src/regraph_pma_cross_row/bank_returns.cpp
  src/regraph_pma_cross_row/bank_join.cpp
  src/regraph_pma_cross_row/packet_pipeline.cpp
  src/regraph_pma_cross_row/publisher.cpp
  src/regraph_pma_cross_row/control.cpp
  src/shared_axi_port.cpp
  src/routed_regraph/source_service.cpp
  src/routed_regraph/scatter.cpp
  src/routed_regraph/transport.cpp
  src/routed_regraph/admission.cpp
  src/routed_regraph/resident_memory.cpp
  src/routed_regraph/composition.cpp
  src/routed_regraph/rounds.cpp
  src/routed_regraph/system.cpp
  src/routed_regraph/fixture.cpp
  src/scheduler.cpp
  src/spine_dirty.cpp
  src/spine_l0.cpp
  src/spine_owner.cpp
  src/spine_pagerank.cpp
  src/spine_split.cpp
  src/spine_sssp_compute.cpp
  src/spine_system.cpp
  src/spine_vertex_lifecycle.cpp
)

target_include_directories(spine_cycle_core PUBLIC include)
target_compile_features(spine_cycle_core PUBLIC cxx_std_20)
target_compile_options(spine_cycle_core PRIVATE -Wall -Wextra -Wpedantic -Werror)
set_target_properties(spine_cycle_core PROPERTIES POSITION_INDEPENDENT_CODE ON)

# The independent author-ReGraph family is not wired into the production SST
# plugin until its complete input, memory, and round boundaries are admitted.
add_library(original_regraph_cycle STATIC
  src/original_regraph/mixed_indexer.cpp
  src/original_regraph/big_requests.cpp
  src/original_regraph/big_source_memory.cpp
  src/original_regraph/big_scatter.cpp
  src/original_regraph/big_routing.cpp
  src/original_regraph/big_gather.cpp
  src/original_regraph/big_merge.cpp
  src/original_regraph/edge_reader.cpp
  src/original_regraph/source_memory.cpp
  src/original_regraph/little_scatter.cpp
  src/original_regraph/write_indexer.cpp
  src/original_regraph/pr_apply.cpp
  src/original_regraph/sssp_apply.cpp
  src/original_regraph/property_writer.cpp
  src/original_regraph/little_gather.cpp
  src/original_regraph/little_merge.cpp)
target_link_libraries(original_regraph_cycle PUBLIC spine_cycle_core)
target_compile_options(original_regraph_cycle PRIVATE -Wall -Wextra -Wpedantic -Werror)

# Independent study input; not part of the production SST plugin.
add_library(original_grasu_cycle STATIC
  src/original_grasu/types.cpp
  src/original_grasu/routing.cpp
  src/original_grasu/edge_reader.cpp
  src/original_grasu/search.cpp
  src/original_grasu/hot_store.cpp
  src/original_grasu/ddr.cpp)
target_link_libraries(original_grasu_cycle PUBLIC spine_cycle_core)
target_compile_options(original_grasu_cycle PRIVATE -Wall -Wextra -Wpedantic -Werror)

add_library(pma_adapter_cycle STATIC src/pma_adapter/reader.cpp)
target_link_libraries(pma_adapter_cycle PUBLIC original_regraph_cycle)
target_compile_options(pma_adapter_cycle PRIVATE -Wall -Wextra -Wpedantic -Werror)

add_executable(persistent_update_host_benchmark
  tools/persistent_update_host_benchmark.cpp)
target_link_libraries(persistent_update_host_benchmark PRIVATE spine_cycle_core)
target_compile_options(persistent_update_host_benchmark PRIVATE
  -Wall -Wextra -Wpedantic -Werror)

if(BUILD_TESTING)
  set(SPINE_SSSP_UDF_REFERENCE "" CACHE FILEPATH "Optional local HLS SSSP UDF correctness reference")
  if(SPINE_SSSP_UDF_REFERENCE)
    if(NOT EXISTS "${SPINE_SSSP_UDF_REFERENCE}")
      message(FATAL_ERROR "SSSP UDF reference does not exist")
    endif()
    add_executable(original_regraph_sssp_source_comparison
      tests/original_regraph/sssp_source_comparison.cpp)
    target_link_libraries(original_regraph_sssp_source_comparison PRIVATE original_regraph_cycle)
    target_compile_definitions(original_regraph_sssp_source_comparison PRIVATE
      SPINE_SSSP_UDF_REFERENCE="${SPINE_SSSP_UDF_REFERENCE}")
    target_compile_options(original_regraph_sssp_source_comparison PRIVATE
      -Wall -Wextra -Wpedantic -Werror)
    add_test(NAME original_regraph_sssp_source_comparison COMMAND original_regraph_sssp_source_comparison)
  endif()

  foreach(sssp_test IN ITEMS udf frontend apply round)
    add_executable(original_regraph_sssp_${sssp_test}_tests
      tests/original_regraph/sssp_${sssp_test}_tests.cpp)
    target_link_libraries(original_regraph_sssp_${sssp_test}_tests PRIVATE original_regraph_cycle)
    target_compile_options(original_regraph_sssp_${sssp_test}_tests PRIVATE
      -Wall -Wextra -Wpedantic -Werror)
    add_test(NAME original_regraph_sssp_${sssp_test}_tests
      COMMAND original_regraph_sssp_${sssp_test}_tests)
  endforeach()

  add_executable(original_regraph_sssp_real_round tests/original_regraph/sssp/real_round.cpp)
  target_link_libraries(original_regraph_sssp_real_round PRIVATE original_regraph_cycle)
  target_compile_options(original_regraph_sssp_real_round PRIVATE -Wall -Wextra -Wpedantic -Werror)

  add_executable(axi_independent_channels_tests tests/axi/independent_channels_tests.cpp)
  target_link_libraries(axi_independent_channels_tests PRIVATE spine_cycle_core)
  target_compile_options(axi_independent_channels_tests PRIVATE -Wall -Wextra -Wpedantic -Werror)
  add_test(NAME axi_independent_channels_tests COMMAND axi_independent_channels_tests)

  add_executable(routed_regraph_fixture_tests tests/routed_regraph/fixture_tests.cpp)
  target_link_libraries(routed_regraph_fixture_tests PRIVATE spine_cycle_core)
  target_compile_options(routed_regraph_fixture_tests PRIVATE -Wall -Wextra -Wpedantic -Werror)
  add_test(NAME routed_regraph_fixture_tests COMMAND routed_regraph_fixture_tests)

  add_executable(routed_regraph_system_tests tests/routed_regraph/system_tests.cpp)
  target_link_libraries(routed_regraph_system_tests PRIVATE spine_cycle_core)
  target_compile_options(routed_regraph_system_tests PRIVATE -Wall -Wextra -Wpedantic -Werror)
  add_test(NAME routed_regraph_system_tests COMMAND routed_regraph_system_tests)

  add_executable(grasu_routed_handoff_tests tests/evaluation_impact/handoff/tests.cpp)
  target_link_libraries(grasu_routed_handoff_tests PRIVATE spine_cycle_core)
  target_compile_options(grasu_routed_handoff_tests PRIVATE -Wall -Wextra -Wpedantic -Werror)
  add_test(NAME grasu_routed_handoff_tests COMMAND grasu_routed_handoff_tests)
  add_executable(grasu_banked_handoff_tests tests/evaluation_impact/handoff/banked.cpp)
  target_link_libraries(grasu_banked_handoff_tests PRIVATE spine_cycle_core)
  target_compile_options(grasu_banked_handoff_tests PRIVATE -Wall -Wextra -Wpedantic -Werror)
  add_test(NAME grasu_banked_handoff_tests COMMAND grasu_banked_handoff_tests)
  add_executable(grasu_cached_handoff_tests tests/evaluation_impact/handoff/cached.cpp)
  target_link_libraries(grasu_cached_handoff_tests PRIVATE spine_cycle_core)
  target_compile_options(grasu_cached_handoff_tests PRIVATE -Wall -Wextra -Wpedantic -Werror)
  add_test(NAME grasu_cached_handoff_tests COMMAND grasu_cached_handoff_tests)

  add_executable(routed_scatter_tests tests/routed_regraph/scatter_tests.cpp)
  target_link_libraries(routed_scatter_tests PRIVATE spine_cycle_core)
  target_compile_options(routed_scatter_tests PRIVATE -Wall -Wextra -Wpedantic -Werror)
  add_test(NAME routed_scatter_tests COMMAND routed_scatter_tests)

  add_executable(routed_source_service_tests tests/routed_regraph/source_service_tests.cpp)
  target_link_libraries(routed_source_service_tests PRIVATE spine_cycle_core)
  target_compile_options(routed_source_service_tests PRIVATE -Wall -Wextra -Wpedantic -Werror)
  add_test(NAME routed_source_service_tests COMMAND routed_source_service_tests)

  add_executable(routed_pma_adapter_tests tests/routed_regraph/adapter_tests.cpp)
  target_link_libraries(routed_pma_adapter_tests PRIVATE spine_cycle_core)
  target_compile_options(routed_pma_adapter_tests PRIVATE -Wall -Wextra -Wpedantic -Werror)
  add_test(NAME routed_pma_adapter_tests COMMAND routed_pma_adapter_tests)

  add_executable(shared_axi_port_tests tests/routed_regraph/shared_axi_tests.cpp)
  target_link_libraries(shared_axi_port_tests PRIVATE spine_cycle_core)
  target_compile_options(shared_axi_port_tests PRIVATE -Wall -Wextra -Wpedantic -Werror)
  add_test(NAME shared_axi_port_tests COMMAND shared_axi_port_tests)

  add_executable(regraph_compute_port_tests tests/routed_regraph/compute_ports_tests.cpp)
  target_link_libraries(regraph_compute_port_tests PRIVATE spine_cycle_core)
  target_compile_options(regraph_compute_port_tests PRIVATE -Wall -Wextra -Wpedantic -Werror)
  add_test(NAME regraph_compute_port_tests COMMAND regraph_compute_port_tests)

  add_executable(original_grasu_execution tests/original_grasu/execution.cpp)
  target_link_libraries(original_grasu_execution PRIVATE original_grasu_cycle)
  target_compile_options(original_grasu_execution PRIVATE -Wall -Wextra -Wpedantic -Werror)
  add_executable(original_grasu_tests tests/original_grasu/component_tests.cpp)
  target_link_libraries(original_grasu_tests PRIVATE original_grasu_cycle)
  target_compile_options(original_grasu_tests PRIVATE -Wall -Wextra -Wpedantic -Werror)
  add_test(NAME original_grasu_tests COMMAND original_grasu_tests)
  add_executable(original_grasu_cache_tests tests/original_grasu/cache_tests.cpp)
  target_link_libraries(original_grasu_cache_tests PRIVATE original_grasu_cycle)
  target_compile_options(original_grasu_cache_tests PRIVATE -Wall -Wextra -Wpedantic -Werror)
  add_test(NAME original_grasu_cache_tests COMMAND original_grasu_cache_tests)

  add_executable(pma_adapter_tests tests/pma_adapter/reader_tests.cpp)
  target_link_libraries(pma_adapter_tests PRIVATE pma_adapter_cycle)
  target_compile_options(pma_adapter_tests PRIVATE -Wall -Wextra -Wpedantic -Werror)
  add_test(NAME pma_adapter_tests COMMAND pma_adapter_tests)

  add_executable(pma_regraph_execution tests/pma_adapter/whole_execution.cpp)
  target_link_libraries(pma_regraph_execution PRIVATE pma_adapter_cycle)
  target_compile_options(pma_regraph_execution PRIVATE -Wall -Wextra -Wpedantic -Werror)

  add_executable(original_regraph_mixed_tests tests/original_regraph/whole_graph/mixed/indexer_tests.cpp)
  target_link_libraries(original_regraph_mixed_tests PRIVATE original_regraph_cycle)
  target_compile_options(original_regraph_mixed_tests PRIVATE -Wall -Wextra -Wpedantic -Werror)
  add_test(NAME original_regraph_mixed_tests COMMAND original_regraph_mixed_tests)

  add_executable(original_regraph_mixed_execution tests/original_regraph/whole_graph/mixed/execution.cpp)
  target_link_libraries(original_regraph_mixed_execution PRIVATE original_regraph_cycle)
  target_compile_options(original_regraph_mixed_execution PRIVATE -Wall -Wextra -Wpedantic -Werror)

  add_executable(original_regraph_big_frontend_tests tests/original_regraph/big_frontend_tests.cpp)
  target_link_libraries(original_regraph_big_frontend_tests PRIVATE original_regraph_cycle)
  target_compile_options(original_regraph_big_frontend_tests PRIVATE -Wall -Wextra -Wpedantic -Werror)
  add_test(NAME original_regraph_big_frontend_tests COMMAND original_regraph_big_frontend_tests)

  add_executable(original_regraph_big_frontend_comparison tests/original_regraph/big_frontend_comparison.cpp)
  target_link_libraries(original_regraph_big_frontend_comparison PRIVATE original_regraph_cycle)
  target_compile_options(original_regraph_big_frontend_comparison PRIVATE -Wall -Wextra -Wpedantic -Werror)

  add_executable(original_regraph_big_tests tests/original_regraph/big_tests.cpp)
  target_link_libraries(original_regraph_big_tests PRIVATE original_regraph_cycle)
  target_compile_options(original_regraph_big_tests PRIVATE -Wall -Wextra -Wpedantic -Werror)
  add_test(NAME original_regraph_big_tests COMMAND original_regraph_big_tests)

  add_executable(original_regraph_big_comparison tests/original_regraph/big_comparison.cpp)
  target_link_libraries(original_regraph_big_comparison PRIVATE original_regraph_cycle)
  target_compile_options(original_regraph_big_comparison PRIVATE -Wall -Wextra -Wpedantic -Werror)
  add_executable(original_regraph_a4_execution tests/original_regraph/whole_graph/a4_execution.cpp)
  target_link_libraries(original_regraph_a4_execution PRIVATE original_regraph_cycle)
  target_compile_options(original_regraph_a4_execution PRIVATE -Wall -Wextra -Wpedantic -Werror)

  add_executable(original_regraph_iteration_tests tests/original_regraph/iteration_tests.cpp)
  target_link_libraries(original_regraph_iteration_tests PRIVATE original_regraph_cycle)
  target_compile_options(original_regraph_iteration_tests PRIVATE -Wall -Wextra -Wpedantic -Werror)
  add_test(NAME original_regraph_iteration_tests COMMAND original_regraph_iteration_tests)

  add_executable(original_regraph_state_tests tests/original_regraph/state_tests.cpp)
  target_link_libraries(original_regraph_state_tests PRIVATE original_regraph_cycle)
  target_compile_options(original_regraph_state_tests PRIVATE -Wall -Wextra -Wpedantic -Werror)
  add_test(NAME original_regraph_state_tests COMMAND original_regraph_state_tests)

  add_executable(original_regraph_state_comparison tests/original_regraph/state_comparison.cpp)
  target_link_libraries(original_regraph_state_comparison PRIVATE original_regraph_cycle)
  target_compile_options(original_regraph_state_comparison PRIVATE -Wall -Wextra -Wpedantic -Werror)

  add_executable(original_regraph_frontend_tests tests/original_regraph/frontend_tests.cpp)
  target_link_libraries(original_regraph_frontend_tests PRIVATE original_regraph_cycle)
  target_compile_options(original_regraph_frontend_tests PRIVATE -Wall -Wextra -Wpedantic -Werror)
  add_test(NAME original_regraph_frontend_tests COMMAND original_regraph_frontend_tests)

  add_executable(original_regraph_gather_tests tests/original_regraph/gather_tests.cpp)
  target_link_libraries(original_regraph_gather_tests PRIVATE original_regraph_cycle)
  target_compile_options(original_regraph_gather_tests PRIVATE -Wall -Wextra -Wpedantic -Werror)
  add_test(NAME original_regraph_gather_tests COMMAND original_regraph_gather_tests)

  add_executable(original_regraph_source_comparison tests/original_regraph/source_comparison.cpp)
  target_link_libraries(original_regraph_source_comparison PRIVATE original_regraph_cycle)
  target_compile_options(original_regraph_source_comparison PRIVATE -Wall -Wextra -Wpedantic -Werror)

  add_executable(sst_hbm_mapper_tests
    tests/sst_hbm_mapper_tests.cpp sst/physical_hbm_mapper.cpp)
  target_include_directories(sst_hbm_mapper_tests PRIVATE sst)
  target_compile_features(sst_hbm_mapper_tests PRIVATE cxx_std_20)
  target_compile_options(sst_hbm_mapper_tests PRIVATE -Wall -Wextra -Wpedantic -Werror)
  add_test(NAME sst_hbm_mapper_tests COMMAND sst_hbm_mapper_tests)

  add_executable(spine_cycle_core_tests tests/core_tests.cpp)
  target_link_libraries(spine_cycle_core_tests PRIVATE spine_cycle_core)
  target_compile_definitions(
    spine_cycle_core_tests PRIVATE SPINE_SOURCE_DIR="${PROJECT_SOURCE_DIR}")
  target_compile_options(spine_cycle_core_tests PRIVATE -Wall -Wextra -Wpedantic -Werror)
  add_test(NAME spine_cycle_core_tests COMMAND spine_cycle_core_tests)

  add_executable(spine_owner_tests tests/spine_owner_tests.cpp)
  target_link_libraries(spine_owner_tests PRIVATE spine_cycle_core)
  target_compile_options(spine_owner_tests PRIVATE -Wall -Wextra -Wpedantic -Werror)
  add_test(NAME spine_owner_tests COMMAND spine_owner_tests)

  add_executable(spine_vertex_lifecycle_tests tests/spine_vertex_lifecycle_tests.cpp)
  target_link_libraries(spine_vertex_lifecycle_tests PRIVATE spine_cycle_core)
  target_compile_options(spine_vertex_lifecycle_tests PRIVATE -Wall -Wextra -Wpedantic -Werror)
  add_test(NAME spine_vertex_lifecycle_tests COMMAND spine_vertex_lifecycle_tests)

  add_executable(grasu_cycle_tests tests/grasu_tests.cpp)
  target_link_libraries(grasu_cycle_tests PRIVATE spine_cycle_core)
  target_compile_options(grasu_cycle_tests PRIVATE -Wall -Wextra -Wpedantic -Werror)
  add_test(NAME grasu_cycle_tests COMMAND grasu_cycle_tests)

  add_executable(grasu_parallel_search_tests tests/grasu_parallel_search_tests.cpp)
  target_link_libraries(grasu_parallel_search_tests PRIVATE spine_cycle_core)
  target_compile_options(grasu_parallel_search_tests PRIVATE -Wall -Wextra -Wpedantic -Werror)
  add_test(NAME grasu_parallel_search_tests COMMAND grasu_parallel_search_tests)

  add_executable(grasu_direct_processor_tests tests/grasu_direct_processor_tests.cpp)
  target_link_libraries(grasu_direct_processor_tests PRIVATE spine_cycle_core)
  target_compile_options(grasu_direct_processor_tests PRIVATE -Wall -Wextra -Wpedantic -Werror)
  add_test(NAME grasu_direct_processor_tests COMMAND grasu_direct_processor_tests)

  add_executable(grasu_cached_processor_tests tests/grasu_cached_processor_tests.cpp)
  target_link_libraries(grasu_cached_processor_tests PRIVATE spine_cycle_core)
  target_compile_options(grasu_cached_processor_tests PRIVATE -Wall -Wextra -Wpedantic -Werror)
  add_test(NAME grasu_cached_processor_tests COMMAND grasu_cached_processor_tests)

  add_executable(grasu_runtime_tests tests/grasu_runtime_tests.cpp)
  target_link_libraries(grasu_runtime_tests PRIVATE spine_cycle_core)
  target_compile_options(grasu_runtime_tests PRIVATE -Wall -Wextra -Wpedantic -Werror)
  add_test(NAME grasu_runtime_tests COMMAND grasu_runtime_tests)
endif()
