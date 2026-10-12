#include <filesystem>
#include <iostream>
#include <stdexcept>

#include "../round_execution.hpp"

namespace rt = routed_regraph_round_test;

int main(int argc, char** argv) {
  try {
    rt::st::require(argc == 8, "usage: round INPUT OUTPUT LATENCY REVERSE MAX_CYCLES EMPTY_EXIT ROW_LINE");
    const auto latency = rt::number(argv[3]), reverse = rt::number(argv[4]);
    const auto maximum = rt::number(argv[5]), empty_exit = rt::number(argv[6]), row_line = rt::number(argv[7]);
    rt::st::require(latency && maximum && reverse <= 1 && row_line <= 1,
                    "invalid bounded service, order, cycle limit or row mode");
    rt::st::require(empty_exit == 0 || (empty_exit == 73 && !row_line), "unsupported adapter arm");
    const auto output = std::filesystem::path(argv[2]);
    rt::st::require(std::filesystem::is_directory(output) && std::filesystem::is_empty(output),
                    "output must be an existing empty directory");
    const auto input = rt::st::Input::load(argv[1]);
    std::cout << "MODEL_CONTROL {\"row_line_reads\":" << row_line
              << ",\"empty_segment_exit_cycles\":" << empty_exit
              << ",\"fixed_rounds\":1,\"hardware_timing_admitted\":false"
              << ",\"strict_resource_match_admitted\":false}\n";
    rt::execute(input, output, latency, reverse != 0, maximum, {empty_exit, row_line != 0, true});
  } catch (const std::exception& error) {
    std::cerr << error.what() << '\n';
    return 1;
  }
}
