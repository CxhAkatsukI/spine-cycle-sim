#include <filesystem>
#include <iostream>
#include <stdexcept>

#include "../round_execution.hpp"

namespace rt = routed_regraph_round_test;

int main(int argc, char** argv) {
  try {
    rt::st::require(argc == 7, "usage: round INPUT OUTPUT LATENCY REVERSE MAX_CYCLES CROSS_ROW");
    const auto latency = rt::number(argv[3]), reverse = rt::number(argv[4]);
    const auto maximum = rt::number(argv[5]), cross = rt::number(argv[6]);
    rt::st::require(latency && maximum && reverse <= 1 && cross <= 1, "invalid bounded model argument");
    const auto output = std::filesystem::path(argv[2]);
    rt::st::require(std::filesystem::is_directory(output) && std::filesystem::is_empty(output),
                    "output must be an existing empty directory");
    const auto input = rt::st::Input::load(argv[1]);
    std::cout << "MODEL_CONTROL {\"version\":\"cross_row_a4_v1\",\"cross_row_pipeline\":" << cross
              << ",\"row_line_reads\":1,\"empty_segment_exit_cycles\":0,\"fixed_rounds\":1"
              << ",\"hardware_timing_admitted\":false,\"strict_resource_match_admitted\":false}\n";
    rt::execute(input, output, latency, reverse != 0, maximum, {0, true, true, cross != 0});
  } catch (const std::exception& error) {
    std::cerr << error.what() << '\n';
    return 1;
  }
}
