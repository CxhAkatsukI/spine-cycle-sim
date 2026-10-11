#include <ap_axi_sdata.h>
#include <ap_int.h>
#include <hls_stream.h>

#include "adapter_fixture.hpp"

#include <iostream>
#include <stdexcept>

using HlsPacket = ap_axiu<512, 0, 0, 0>;
// Vitis 2024.1 defines non-inline specializations in its headers. Keep the
// unmodified production source and this optional probe in one translation unit.
#include GRASU_ADAPTER_SOURCE

namespace {
using namespace routed_adapter_test;

void check(const Data &data) {
  std::vector<ap_uint<64>> rows(data.rows.size() / 2);
  for (std::size_t row = 0; row < rows.size(); ++row)
    rows[row] = (ap_uint<64>(data.rows[row * 2 + 1]) << 32) | data.rows[row * 2];
  std::array<std::vector<ap_uint<512>>, 4> pma;
  for (std::size_t bank = 0; bank < 4; ++bank) {
    pma[bank].resize(data.pma[bank].size() / 16);
    for (std::size_t word = 0; word < data.pma[bank].size(); ++word)
      pma[bank][word / 16].range(word % 16 * 32 + 31, word % 16 * 32) = data.pma[bank][word];
  }
  const auto &part = data.partition;
  hls::stream<HlsPacket> output;
  pma_to_regraph_adapter(pma[0].data(), pma[1].data(), pma[2].data(), pma[3].data(),
      rows.data(), part.vertices, part.slots, part.cache_segments_per_half,
      part.destination_base, part.destination_vertices, output);
  for (const auto &expected : data.expected) {
    if (output.empty()) throw std::runtime_error("HLS output truncated");
    const auto packet = output.read();
    if (bool(packet.last) != expected.last || packet.keep != ap_uint<64>(-1) ||
        packet.strb != ap_uint<64>(-1)) throw std::runtime_error("HLS AXIS sideband mismatch");
    for (unsigned lane = 0; lane < 8; ++lane) {
      if (packet.data.range(lane * 64 + 31, lane * 64).to_uint() != expected.sources[lane] ||
          packet.data.range(lane * 64 + 63, lane * 64 + 32).to_uint() != expected.destinations[lane])
        throw std::runtime_error("HLS packet differs from simulator's word-level fixture");
    }
  }
  if (!output.empty()) throw std::runtime_error("HLS output has extra packets");
}
} // namespace

int main() {
  try {
#if GRASU_REGRAPH_WEIGHTED_PMA
    constexpr auto format = ReGraphPmaFormat::kWeighted;
#elif GRASU_REGRAPH_DESTINATION_ONLY
    constexpr auto format = ReGraphPmaFormat::kDestination;
#else
    constexpr auto format = ReGraphPmaFormat::kUnitWeight;
#endif
    std::size_t cases = 0;
    for (const auto vertices : {0U, 1U, 8U, 9U, 65U, 1025U})
      for (bool at_end : {false, true})
        for (bool empty : {false, true}) {
          check(Data(vertices, at_end, empty, format));
          ++cases;
        }
    for (const auto cache : {0U, 1U, 4U}) {
      check(Data(9, true, false, format, cache));
      ++cases;
    }
    std::cout << "HLS shared-fixture packet check PASS cases=" << cases << '\n';
    return 0;
  } catch (const std::exception &error) {
    std::cerr << error.what() << '\n';
    return 1;
  }
}
