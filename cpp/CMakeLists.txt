add_library(spine_cycle_core STATIC
  src/axi.cpp
  src/banked_memory.cpp
  src/memory_backend.cpp
  src/scheduler.cpp
  src/spine_l0.cpp
)

target_include_directories(spine_cycle_core PUBLIC include)
target_compile_features(spine_cycle_core PUBLIC cxx_std_20)
target_compile_options(spine_cycle_core PRIVATE -Wall -Wextra -Wpedantic -Werror)
set_target_properties(spine_cycle_core PROPERTIES POSITION_INDEPENDENT_CODE ON)

if(BUILD_TESTING)
  add_executable(spine_cycle_core_tests tests/core_tests.cpp)
  target_link_libraries(spine_cycle_core_tests PRIVATE spine_cycle_core)
  target_compile_definitions(
    spine_cycle_core_tests PRIVATE SPINE_SOURCE_DIR="${PROJECT_SOURCE_DIR}")
  target_compile_options(spine_cycle_core_tests PRIVATE -Wall -Wextra -Wpedantic -Werror)
  add_test(NAME spine_cycle_core_tests COMMAND spine_cycle_core_tests)
endif()
