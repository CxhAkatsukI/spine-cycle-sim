#pragma once

#include "frontend_support.hpp"
#include "spine_sim/original_regraph/big_frontend_types.hpp"

namespace original_regraph_big_frontend_test {
namespace rg = spine::sim::original_regraph;
using original_regraph_frontend_test::require;
using original_regraph_frontend_test::append_word;

inline std::uint32_t property(std::uint32_t vertex) { return 17 + vertex; }
inline std::vector<rg::EdgeBurst> fixture(unsigned id) {
  require(id < 6, "unknown Big frontend fixture");
  const unsigned bursts = id == 4 ? 1 : (id == 0 ? 8 : 64);
  std::vector<rg::EdgeBurst> result(bursts);
  for (unsigned burst = 0; burst < bursts; ++burst) for (unsigned lane = 0; lane < 8; ++lane) {
    const auto index = burst * 8 + lane;
    unsigned source = 0;
    if (id == 0) source = index / 8;
    else if (id == 1) source = index * 13;
    else if (id == 2) source = (17 + burst / 2) * 16 + (burst % 2) * 4 + lane / 2;
    else if (id == 3) source = (burst / 4) * 8192 + (burst % 4) * 64 + lane * 3;
    else if (id == 5) source = 4096 + (index / 2) * 17;
    auto destination = static_cast<unsigned>((index * 7919ull) % 524288);
    if (id == 4) { source = 0x80000000u; destination = rg::kDummyDestination; }
    result[burst][lane] = {source, destination};
  }
  if (id != 4) {
    const auto last_source = result.back()[3].source;
    for (unsigned lane = 4; lane < 8; ++lane) result.back()[lane] = {last_source | 0x80000000u, rg::kDummyDestination};
  }
  return result;
}

inline std::vector<rg::CachelineRequest> requests(const std::vector<rg::EdgeBurst>& input) {
  std::vector<rg::CachelineRequest> result{{0, 0, false}};
  std::uint32_t last_line = 0;
  for (const auto& burst : input) {
    const auto last = (burst.back().source & 0x7fffffffu) / 16;
    if (last != last_line) for (unsigned lane = 0; lane < 8; ++lane) {
      const auto line = (burst[lane].source & 0x7fffffffu) / 16;
      if (line != last_line) result.push_back({line, lane, false});
    }
    last_line = last;
  }
  result.push_back({0, 7, true});
  return result;
}

inline std::vector<rg::UpdateBurst> updates(const std::vector<rg::EdgeBurst>& input, unsigned offset) {
  std::vector<rg::UpdateBurst> result(input.size());
  for (std::size_t burst = 0; burst < input.size(); ++burst) for (unsigned lane = 0; lane < 8; ++lane) {
    const auto& edge = input[burst][lane];
    const auto destination = edge.destination & rg::kDummyDestination
        ? ((0x7fffffffu - offset) & 0x7ffffu) | rg::kDummyDestination : edge.destination;
    result[burst][lane] = {destination, property(edge.source & 0x7fffffffu)};
  }
  return result;
}

}  // namespace original_regraph_big_frontend_test
