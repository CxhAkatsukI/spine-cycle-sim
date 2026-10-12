#include <filesystem>
#include <iostream>
#include <stdexcept>

#include "../round_execution.hpp"

namespace rt = routed_regraph_round_test;

int main(int argc, char** argv) {
  try {
    rt::st::require(argc >= 7 && argc <= 11, "usage: round INPUT OUTPUT LATENCY REVERSE MAX_CYCLES TILE_ROWS [PACKET_PIPELINE [BANK_STREAM [READ_BEATS [BANK_LINES]]]]");
    const auto latency = rt::number(argv[3]), reverse = rt::number(argv[4]);
    const auto maximum = rt::number(argv[5]), rows = rt::number(argv[6]);
    const auto pipeline = argc >= 8 ? rt::number(argv[7]) : 0;
    const auto bank = argc >= 9 ? rt::number(argv[8]) : 0;
    const auto beats = argc >= 10 ? rt::number(argv[9]) : 0;
    const auto bank_lines = argc == 11 ? rt::number(argv[10]) : 128;
    rt::st::require(latency && maximum && reverse <= 1 && (rows == 8 || rows == 128 || rows == 1024) &&
                    pipeline <= 1 && (!pipeline || rows == 1024) && bank <= 1 && (!bank || pipeline) &&
                    beats <= 1 && (!beats || bank) && (bank_lines == 128 || bank_lines == 256) &&
                    (bank_lines == 128 || bank),
                    "invalid bounded directory tile argument");
    const auto output = std::filesystem::path(argv[2]);
    rt::st::require(std::filesystem::is_directory(output) && std::filesystem::is_empty(output),
                    "output must be an existing empty directory");
    const auto input = rt::st::Input::load(argv[1]);
    std::cout << "MODEL_CONTROL {\"version\":\"directory_tile_v1\",\"directory_cache_rows\":"
              << rows << ",\"cross_row_pipeline\":1,\"row_line_reads\":1,\"fixed_rounds\":1"
              << ",\"hardware_timing_admitted\":false,\"strict_resource_match_admitted\":false";
    if (pipeline) std::cout << ",\"packet_pipeline\":true";
    if (bank) std::cout << ",\"bank_stream\":true";
    if (beats) std::cout << ",\"bank_read_beats\":true";
    if (bank_lines != 128) std::cout << ",\"bank_fifo_lines\":" << bank_lines;
    std::cout << "}\n";
    rt::execute(input, output, latency, reverse != 0, maximum,
                {0, true, true, true, false, rows, pipeline != 0, bank != 0, beats != 0, bank_lines});
  } catch (const std::exception& error) {
    std::cerr << error.what() << '\n';
    return 1;
  }
}
