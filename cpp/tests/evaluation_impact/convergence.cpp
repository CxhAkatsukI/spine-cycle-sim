#include <iostream>

#include "a4.hpp"
#include "k4.hpp"
#include "../routed_regraph/round_execution.hpp"

namespace ei = evaluation_impact;

int main(int argc, char** argv) {
  try {
    ei::st::require(argc == 7 || argc == 8,
                   "usage: demo INPUT OUTPUT LATENCY REVERSE MAX_CYCLES ARM [PROGRESS_DIRECTORY]");
    const auto selected = ei::control(argv[6]);
    const auto input = ei::st::Input::load(argv[1]);
    const auto output = std::filesystem::path(argv[2]);
    ei::st::require(std::filesystem::is_directory(output), "missing unique output directory");
    const auto latency = routed_regraph_round_test::number(argv[3]);
    const auto reverse = routed_regraph_round_test::number(argv[4]);
    const auto maximum = routed_regraph_round_test::number(argv[5]);
    ei::st::require(latency > 0 && reverse <= 1 && maximum > 0, "invalid demo bound");
    const auto progress = argc == 8 ? std::filesystem::path(argv[7]) : std::filesystem::path{};
    ei::st::require(argc == 7 || (selected.bank_stream && std::filesystem::is_directory(progress) &&
        std::filesystem::is_empty(progress) && !std::filesystem::equivalent(output, progress)),
        "progress requires bank_stream and a separate empty directory");
    const auto oracle = ei::closure(input, 128);
    if (selected.original) ei::a4(input, oracle, output, latency, reverse, maximum, selected);
    else ei::k4(input, oracle, output, latency, reverse, maximum, selected, progress);
  } catch (const std::exception& error) { std::cerr << error.what() << '\n'; return 1; }
}
