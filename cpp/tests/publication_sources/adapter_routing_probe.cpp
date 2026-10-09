#include <filesystem>
#include <fstream>
#include <iostream>
#include <stdexcept>

#include "pma_to_regraph_adapter.cpp"
#include "../pma_adapter/fixture_data.hpp"

int main(int argc, char** argv) {
  try {
    if (argc != 2 || !std::filesystem::is_directory(argv[1])) throw std::runtime_error("usage: adapter_routing_probe CAPTURE_DIR");
    for (unsigned cache : {0u, 1u, 3u}) {
      const pma_adapter_test::Data data(cache);
      std::array<std::vector<ap_uint<512>>, 4> buffers;
      for (unsigned route = 0; route < 4; ++route) {
        for (unsigned index = 0; index < data.buffers[route].size(); index += 16) {
          ap_uint<512> packed = 0;
          for (unsigned lane = 0; lane < 16; ++lane) packed.range(lane * 32 + 31, lane * 32) = data.buffers[route][index + lane];
          buffers[route].push_back(packed);
        }
      }
      std::vector<ap_uint<64>> rows;
      for (unsigned source = 0; source < data.vertices; ++source) rows.push_back(
          (std::uint64_t{data.rows[source * 2 + 1]} << 32) | data.rows[source * 2]);
      hls::stream<edge_burst_pkt_t> output;
      pma_to_regraph_adapter(buffers[0].data(), buffers[1].data(), buffers[2].data(), buffers[3].data(),
          rows.data(), data.vertices, data.slots, cache, data.destination, data.destination_vertices, output);
      const auto path = std::filesystem::path(argv[1]) / ("cache" + std::to_string(cache) + ".u32le");
      if (std::filesystem::exists(path)) throw std::runtime_error("refuse to overwrite adapter routing capture");
      std::ofstream stream(path, std::ios::binary);
      unsigned checked = 0;
      while (!output.empty()) {
        const auto packet = output.read();
        if (packet.keep != ap_uint<64>(-1) || packet.strb != ap_uint<64>(-1) ||
            packet.last != (checked + 16 == data.expected_global.size())) throw std::runtime_error("adapter routing AXIS control");
        for (unsigned word = 0; word < 16; ++word) {
          const auto value = packet.data.range(word * 32 + 31, word * 32).to_uint();
          if (checked >= data.expected_global.size() || value != data.expected_global[checked++]) throw std::runtime_error("adapter routing packet/stale copy mismatch");
          for (unsigned byte = 0; byte < 4; ++byte) stream.put(static_cast<char>(value >> (byte * 8)));
        }
      }
      stream.close();
      if (!stream.good() || checked != data.expected_global.size()) throw std::runtime_error("adapter routing capture extent");
      std::cout << "ADAPTER_ROUTING {\"cache_segments\":" << cache << ",\"passed\":true,\"checked_words\":" << checked << "}\n";
    }
    return 0;
  } catch (const std::exception& error) { std::cerr << error.what() << '\n'; return 1; }
}
