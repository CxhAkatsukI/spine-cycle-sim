#include <filesystem>
#include <iostream>
#include <stdexcept>
#include "../round_execution.hpp"

namespace st = original_regraph_sssp_real_test;
namespace rt = routed_regraph_round_test;

int main(int argc, char** argv) {
  try {
    st::require(argc == 7, "usage: round INPUT OUTPUT LATENCY REVERSE MAX_CYCLES EMPTY_EXIT");
    const auto latency = rt::number(argv[3]), reverse = rt::number(argv[4]);
    const auto maximum = rt::number(argv[5]), empty_exit = rt::number(argv[6]);
    st::require(latency && maximum && reverse <= 1, "invalid bounded service, order or cycle limit");
    st::require(empty_exit == 73 || empty_exit == 0, "EMPTY_EXIT must be 73 or 0");
    const auto output = std::filesystem::path(argv[2]);
    st::require(std::filesystem::is_directory(output) && std::filesystem::is_empty(output),
                "output must be an existing empty directory");
    const auto input = st::Input::load(argv[1]);
    std::cout << "SENSITIVITY {\"mode\":\""
              << (empty_exit == 73 ? "legacy_v4_control" : "empty_helper_bypass_uncalibrated")
              << "\",\"empty_segment_exit_cycles\":" << empty_exit
              << ",\"hardware_timing_admitted\":false,\"publication_match_admitted\":false}\n";
    rt::execute(input, output, latency, reverse != 0, maximum, {empty_exit, false, false});
  } catch (const std::exception& error) {
    std::cerr << error.what() << '\n';
    return 1;
  }
}
