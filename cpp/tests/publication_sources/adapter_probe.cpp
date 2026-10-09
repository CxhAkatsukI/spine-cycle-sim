#include <filesystem>
#include <fstream>
#include <iostream>

#include "pma_to_regraph_adapter.cpp"
#include "adapter/input.hpp"

namespace ac = adapter_source_control;

int main(int argc, char** argv) {
  try {
    ac::require(argc == 3, "usage: adapter_source INPUT_DIR OUTPUT_DIR");
    const ac::Input input(argv[1]); const std::filesystem::path directory(argv[2]);
    ac::require(std::filesystem::is_directory(directory) && !std::filesystem::exists(directory / "adapter_edges.u32le"), "adapter output directory/overwrite");
    std::ofstream capture(directory / "adapter_edges.u32le", std::ios::binary);
    ac::require(capture.is_open(), "adapter capture open");
    std::uint64_t logical = 0, physical = 0, row_reads = 0; std::array<std::uint64_t, 4> reads{};
    for (unsigned index = 0; index < input.tasks.size(); ++index) {
      const auto& task = input.tasks[index]; const auto segments = task.slots / 16;
      std::array<std::vector<ap_uint<512>>, 4> memory;
      for (unsigned buffer = 0; buffer < 4; ++buffer) memory[buffer].resize(std::max<unsigned>(131072, (segments + (buffer < 2)) / 2));
      for (unsigned segment = 0; segment < segments; ++segment) {
        ap_uint<512> packed = 0;
        for (unsigned lane = 0; lane < 16; ++lane) packed.range(lane * 32 + 31, lane * 32) = input.pma[task.pma_offset + segment * 16 + lane];
        const auto half = (segment & 1) * 2;
        memory[half][segment / 2] = packed; memory[half + 1][segment / 2] = packed;
        ++reads[half + (segment / 2 >= 131072)];
      }
      std::vector<ap_uint<64>> rows(input.graph.vertices);
      for (unsigned source = 0; source < rows.size(); ++source) {
        rows[source] = (std::uint64_t{input.rows[task.row_offset + source * 2 + 1]} << 32) | input.rows[task.row_offset + source * 2];
      }
      hls::stream<edge_burst_pkt_t> output;
      pma_to_regraph_adapter(memory[0].data(), memory[1].data(), memory[2].data(), memory[3].data(), rows.data(),
          input.graph.vertices, task.slots, 131072, task.destination, 65536, output);
      row_reads += input.graph.vertices + 1ull;
      std::uint64_t emitted = 0;
      for (unsigned source = 0; source < input.graph.vertices; ++source) {
        const auto begin = input.rows[task.row_offset + source * 2 + 1], end = input.rows[task.row_offset + source * 2];
        for (unsigned slot = begin; slot < end; slot += 8) {
          ac::require(!output.empty(), "adapter lost AXIS burst"); const auto packet = output.read(); emitted += 8;
          ac::require(packet.keep == ap_uint<64>(-1) && packet.strb == ap_uint<64>(-1) && packet.last == (emitted == task.slots), "adapter keep/strb/TLAST");
          for (unsigned lane = 0; lane < 8; ++lane) {
            const auto word = input.pma[task.pma_offset + slot + lane]; const bool dummy = word >> 31;
            const auto expected_source = source | (dummy ? 0x80000000u : 0);
            const auto expected_destination = (task.destination + (word & 0x7ffffu)) | (dummy ? 0x80000000u : 0);
            const auto observed_source = packet.data.range(lane * 64 + 31, lane * 64).to_uint();
            const auto observed_destination = packet.data.range(lane * 64 + 63, lane * 64 + 32).to_uint();
            ac::require(observed_source == expected_source && observed_destination == expected_destination, "adapter exact packet value/order");
            for (const auto value : {observed_source, observed_destination}) for (unsigned byte = 0; byte < 4; ++byte) capture.put(static_cast<char>(value >> (byte * 8)));
            logical += !dummy; ++physical;
          }
        }
      }
      ac::require(output.empty() && emitted == task.slots, "adapter extra AXIS burst");
    }
    capture.close(); ac::require(capture.good() && logical == input.graph.logical_edges, "adapter capture or logical conservation");
    std::cout << "ADAPTER_SOURCE {\"passed\":true,\"tasks\":" << input.tasks.size() << ",\"vertices\":" << input.graph.vertices
              << ",\"logical_edges\":" << logical << ",\"physical_edges\":" << physical << ",\"dummy_edges\":" << physical - logical
              << ",\"row_word_reads\":" << row_reads << ",\"pma_segment_reads\":[" << reads[0] << ',' << reads[1] << ',' << reads[2] << ',' << reads[3]
              << "],\"source_row_read_bytes\":" << row_reads * 8 << ",\"source_pma_read_bytes\":" << physical * 4 << "}\n";
    return 0;
  } catch (const std::exception& error) { std::cerr << error.what() << '\n'; return 1; }
}
