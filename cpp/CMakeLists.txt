add_library(spine_cycle_core STATIC
  src/algorithm.cpp
  src/algorithm_pipeline.cpp
  src/axi.cpp
  src/banked_memory.cpp
  src/grasu.cpp
  src/grasu_native.cpp
  src/grasu_regraph.cpp
  src/grasu_regraph_runtime.cpp
  src/grasu_sharded_update.cpp
  src/memory_backend.cpp
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
  src/original_regraph/property_writer.cpp
  src/original_regraph/little_gather.cpp
  src/original_regraph/little_merge.cpp)
target_link_libraries(original_regraph_cycle PUBLIC spine_cycle_core)
target_compile_options(original_regraph_cycle PRIVATE -Wall -Wextra -Wpedantic -Werror)

add_executable(persistent_update_host_benchmark
  tools/persistent_update_host_benchmark.cpp)
target_link_libraries(persistent_update_host_benchmark PRIVATE spine_cycle_core)
target_compile_options(persistent_update_host_benchmark PRIVATE
  -Wall -Wextra -Wpedantic -Werror)

if(BUILD_TESTING)
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

  add_executable(grasu_runtime_tests tests/grasu_runtime_tests.cpp)
  target_link_libraries(grasu_runtime_tests PRIVATE spine_cycle_core)
  target_compile_options(grasu_runtime_tests PRIVATE -Wall -Wextra -Wpedantic -Werror)
  add_test(NAME grasu_runtime_tests COMMAND grasu_runtime_tests)
endif()
