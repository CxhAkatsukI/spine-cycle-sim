#pragma once

#include <map>

#include "../whole_graph/input.hpp"
#include "spine_sim/original_regraph/udf.hpp"
#include "spine_sim/routed_regraph.hpp"

namespace original_regraph_sssp_real_test {
namespace wt = original_regraph_whole_test;
namespace rg = spine::sim::original_regraph;
using wt::require;

struct Input {
  wt::Input compact;
  std::vector<spine::sim::GraSuEdge> edges;
  spine::sim::AlgorithmInitialState initial;

  static Input load(const std::filesystem::path& directory) {
    Input result;
    auto& c = result.compact;
    // Original geometry is shared; PR initialization arithmetic is not SSSP work.
    c = wt::Input::load_layout(directory);
    const auto weights = wt::read_words(directory / "sssp_weights.u32le", c.logical_edges);
    const auto state = wt::read_words(directory / "sssp_initial.u32le", c.aligned_vertices);
    const auto packed = wt::read_words(directory / "sssp_tasks.u32le", c.edge_words.size());
    require(weights.size() == c.logical_edges && state.size() == c.aligned_vertices &&
            packed.size() == c.edge_words.size(), "SSSP overlay extent mismatch");
    std::map<std::pair<std::uint32_t, std::uint32_t>, std::uint32_t> remaining;
    result.initial.primary.resize(c.vertices);
    c.expected = state;
    for (auto& word : c.expected) word &= rg::kSsspValueMask;
    for (std::uint32_t source = 0; source < c.vertices; ++source) {
      const auto distance = state[source] & rg::kSsspValueMask;
      require(distance <= rg::kSsspInfinity, "SSSP initial distance outside ABI");
      result.initial.primary[source] = distance == rg::kSsspInfinity
          ? spine::sim::GraphAlgorithmPolicy::kSsspInfinity : distance;
      if (state[source] & rg::kSsspActive) result.initial.active_vertices.push_back(source);
      for (auto edge = c.offsets[source]; edge < c.offsets[source + 1]; ++edge) {
        const auto destination = c.destinations[edge], weight = weights[edge];
        require(weight > 0 && weight <= 4095 &&
                remaining.emplace(std::pair{source, destination}, weight).second,
                "SSSP control requires unique pairs and positive 12-bit weights");
        result.edges.push_back({source, destination, static_cast<std::uint16_t>(weight), false});
        if (!(state[source] & rg::kSsspActive) || distance == rg::kSsspInfinity) continue;
        const auto candidate = std::uint64_t{distance} + weight;
        require(candidate < rg::kSsspInfinity, "SSSP control candidate reaches infinity");
        auto& expected = c.expected[destination];
        if (candidate < (expected & rg::kSsspValueMask))
          expected = static_cast<std::uint32_t>(candidate) | rg::kSsspActive;
      }
    }
    for (std::size_t vertex = c.vertices; vertex < state.size(); ++vertex)
      require(state[vertex] == 0, "nonzero SSSP padded state");
    for (const auto& task : c.tasks) for (std::size_t i = 0; i < task.words; i += 2) {
      const auto index = task.offset_words + i;
      require(packed[index] == c.edge_words[index], "overlay changed original source/order/padding");
      const auto original_destination = c.edge_words[index + 1];
      if (original_destination & rg::kSsspActive) {
        require(packed[index + 1] == original_destination, "overlay changed dummy padding");
        continue;
      }
      const auto source = packed[index] & rg::kSsspValueMask;
      const auto found = remaining.find({source, original_destination});
      require(found != remaining.end(), "task edge absent or repeated in weighted CSR");
      require(packed[index + 1] == ((original_destination - task.destination) | (found->second << 19)),
              "weighted task localization or weight differs from CSR");
      remaining.erase(found);
    }
    require(remaining.empty(), "weighted task capture omitted a logical edge");
    c.initial = state;
    c.edge_words = packed;
    return result;
  }
};
}  // namespace original_regraph_sssp_real_test
