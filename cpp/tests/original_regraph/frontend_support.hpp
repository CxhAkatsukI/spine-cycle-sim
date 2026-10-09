#pragma once

#include <memory>
#include <stdexcept>
#include <string>
#include <vector>

#include "spine_sim/original_regraph/edge_reader.hpp"
#include "spine_sim/original_regraph/little_scatter.hpp"
#include "spine_sim/original_regraph/source_memory.hpp"
#include "spine_sim/original_regraph/little_merge.hpp"
#include "spine_sim/scheduler.hpp"
#include "memory_fixture.hpp"

namespace original_regraph_frontend_test {
namespace rg = spine::sim::original_regraph;
using spine::sim::Fifo;

inline void require(bool value, const std::string& message) {
  if (!value) throw std::runtime_error(message);
}

struct Options {
  std::size_t little{1};
  std::size_t fifo_depth{8};
  std::uint64_t memory_latency{64};
  std::size_t outstanding{16};
  std::size_t property_vertices{65536};
  bool gather{};
  bool reverse_registration{};
  std::uint64_t sink_interval{1};
  std::uint64_t sink_start{};
  std::uint64_t max_cycles{1000000};
  std::uint32_t destination_offset{};
};

inline spine::sim::AxiConfig axi_config(unsigned initiator, std::size_t channel,
                                       const Options& options) {
  return original_regraph_memory_test::axi_config(initiator, channel, options.outstanding);
}

inline void append_word(std::vector<std::uint8_t>& bytes, std::uint32_t value) {
  for (unsigned byte = 0; byte < 4; ++byte) bytes.push_back((value >> (byte * 8)) & 255u);
}

inline std::vector<std::uint8_t> edge_bytes(const std::vector<rg::EdgeBurst>& edges,
                                           std::uint32_t destination_offset) {
  std::vector<std::uint8_t> result;
  for (const auto& burst : edges) {
    for (const auto edge : burst) {
      append_word(result, edge.source);
      append_word(result, edge.destination & rg::kDummyDestination
          ? 0xffffffffu : edge.destination + destination_offset);
    }
  }
  return result;
}

inline std::vector<rg::EdgeBurst> fixture(const std::vector<unsigned>& rounds,
                                         unsigned pipeline = 0) {
  std::vector<rg::EdgeBurst> result;
  for (const auto round : rounds) {
    for (unsigned index = 0; index < 4; ++index) {
      rg::EdgeBurst burst;
      for (unsigned lane = 0; lane < 8; ++lane) {
        burst[lane] = {round * 4096 + index * 101 + lane * 13 + pipeline * 17,
                       pipeline * 32 + index * 8 + lane};
      }
      result.push_back(burst);
    }
  }
  require(!result.empty(), "nonempty Scatter fixture required");
  for (unsigned lane = 4; lane < 8; ++lane) {
    result.back()[lane].source |= 1u << 31;
    result.back()[lane].destination = rg::kDummyDestination;
  }
  return result;
}

inline rg::UpdateBurst oracle(const rg::EdgeBurst& edge, std::uint32_t destination_offset = 0) {
  rg::UpdateBurst result;
  for (unsigned lane = 0; lane < 8; ++lane) {
    const auto destination = edge[lane].destination & rg::kDummyDestination
        ? ((0x7fffffffu - destination_offset) & 0x7ffffu) | rg::kDummyDestination
        : edge[lane].destination;
    result[lane] = {destination, 17 + (edge[lane].source & 0x7fffffffu) % 31};
  }
  return result;
}

}  // namespace original_regraph_frontend_test
