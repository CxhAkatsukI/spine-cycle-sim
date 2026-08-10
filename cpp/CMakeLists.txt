add_library(spine_cycle_core STATIC
  src/algorithm.cpp
  src/algorithm_pipeline.cpp
  src/axi.cpp
  src/banked_memory.cpp
  src/grasu.cpp
  src/grasu_native.cpp
  src/grasu_regraph.cpp
  src/memory_backend.cpp
  src/scheduler.cpp
  src/spine_dirty.cpp
  src/spine_l0.cpp
  src/spine_owner.cpp
  src/spine_pagerank.cpp
  src/spine_split.cpp
  src/spine_system.cpp
  src/spine_vertex_lifecycle.cpp
)

target_include_directories(spine_cycle_core PUBLIC include)
target_compile_features(spine_cycle_core PUBLIC cxx_std_20)
target_compile_options(spine_cycle_core PRIVATE -Wall -Wextra -Wpedantic -Werror)
set_target_properties(spine_cycle_core PROPERTIES POSITION_INDEPENDENT_CODE ON)

add_executable(persistent_update_host_benchmark
  tools/persistent_update_host_benchmark.cpp)
target_link_libraries(persistent_update_host_benchmark PRIVATE spine_cycle_core)
target_compile_options(persistent_update_host_benchmark PRIVATE
  -Wall -Wextra -Wpedantic -Werror)

if(BUILD_TESTING)
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
endif()
