#pragma once

#include <algorithm>
#include <functional>
#include <queue>

#include "../original_regraph/sssp/real_input.hpp"

namespace evaluation_impact {
namespace st = original_regraph_sssp_real_test;
namespace wt = original_regraph_whole_test;
namespace rg = spine::sim::original_regraph;

struct Oracle {
  std::vector<std::vector<std::uint32_t>> states;
  std::vector<std::size_t> active;
};

inline Oracle closure(const st::Input& input, std::size_t max_rounds) {
  Oracle result;
  auto state = input.compact.initial;
  for (std::size_t round = 0; round < max_rounds; ++round) {
    auto next = state;
    for (auto& word : next) word &= rg::kSsspValueMask;
    for (const auto& edge : input.edges) {
      const auto word = state.at(edge.source);
      if (!(word & rg::kSsspActive) || (word & rg::kSsspValueMask) == rg::kSsspInfinity) continue;
      const auto candidate = std::uint64_t{word & rg::kSsspValueMask} + edge.weight;
      st::require(candidate < rg::kSsspInfinity, "oracle arithmetic outside admitted domain");
      auto& target = next.at(edge.destination);
      if (candidate < (target & rg::kSsspValueMask)) target = candidate | rg::kSsspActive;
    }
    const auto count = static_cast<std::size_t>(std::count_if(next.begin(), next.end(),
        [](auto word) { return (word & rg::kSsspActive) != 0; }));
    result.states.push_back(next);
    result.active.push_back(count);
    state = std::move(next);
    if (!count) break;
  }
  st::require(!result.active.empty() && !result.active.back(), "oracle did not converge");

  // A separate priority-queue closure checks the synchronous frontier oracle.
  using Item = std::pair<std::uint32_t, std::uint32_t>;
  std::priority_queue<Item, std::vector<Item>, std::greater<Item>> queue;
  auto distance = input.compact.initial;
  for (std::uint32_t v = 0; v < input.compact.vertices; ++v) {
    distance[v] &= rg::kSsspValueMask;
    if (distance[v] != rg::kSsspInfinity) queue.emplace(distance[v], v);
  }
  for (std::size_t v = input.compact.vertices; v < distance.size(); ++v) distance[v] = 0;
  while (!queue.empty()) {
    const auto [value, source] = queue.top(); queue.pop();
    if (distance[source] != value) continue;
    for (auto index = input.compact.offsets[source]; index < input.compact.offsets[source + 1]; ++index) {
      const auto& edge = input.edges.at(index);
      const auto candidate = std::uint64_t{value} + edge.weight;
      st::require(candidate < rg::kSsspInfinity, "Dijkstra arithmetic outside admitted domain");
      if (candidate < distance[edge.destination]) {
        distance[edge.destination] = candidate;
        queue.emplace(candidate, edge.destination);
      }
    }
  }
  st::require(distance == result.states.back(), "frontier result differs from independent shortest-path closure");
  return result;
}
}  // namespace evaluation_impact
