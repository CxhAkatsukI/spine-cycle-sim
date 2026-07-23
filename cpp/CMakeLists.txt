add_library(spine_cycle_core STATIC
  src/banked_memory.cpp
  src/scheduler.cpp
)

target_include_directories(spine_cycle_core PUBLIC include)
target_compile_features(spine_cycle_core PUBLIC cxx_std_20)
target_compile_options(spine_cycle_core PRIVATE -Wall -Wextra -Wpedantic -Werror)

if(BUILD_TESTING)
  add_executable(spine_cycle_core_tests tests/core_tests.cpp)
  target_link_libraries(spine_cycle_core_tests PRIVATE spine_cycle_core)
  target_compile_options(spine_cycle_core_tests PRIVATE -Wall -Wextra -Wpedantic -Werror)
  add_test(NAME spine_cycle_core_tests COMMAND spine_cycle_core_tests)
endif()
