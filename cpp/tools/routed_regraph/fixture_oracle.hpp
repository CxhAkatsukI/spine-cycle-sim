#pragma once

#include "weighted_pma_graph.hpp"

#include <queue>

namespace routed_fixture {
using Edge = grasu::integration::WeightedEdgeRecord;
constexpr std::uint32_t inf = 0xffffffffU;
using Adjacency = std::vector<std::vector<std::pair<std::uint32_t, std::uint16_t>>>;

inline Adjacency adjacency(std::size_t vertices, const std::vector<Edge> &edges) {
  Adjacency result(vertices);
  for (const auto &edge : edges) result.at(edge.source).push_back({edge.destination, edge.weight});
  return result;
}

inline std::vector<std::uint32_t> distances(const Adjacency &graph, std::uint32_t source) {
  std::vector<std::uint32_t> state(graph.size(), inf);
  using Entry = std::pair<std::uint32_t, std::uint32_t>;
  std::priority_queue<Entry, std::vector<Entry>, std::greater<Entry>> queue;
  state.at(source) = 0;
  queue.push({0, source});
  while (!queue.empty()) {
    const auto [distance, vertex] = queue.top();
    queue.pop();
    if (distance != state[vertex]) continue;
    for (const auto &[dst, weight] : graph[vertex]) {
      const auto value = std::uint64_t(distance) + weight;
      if (value >= 0x7ffffffeU) throw std::invalid_argument("fixture reaches routed infinity");
      if (value < state[dst]) { state[dst] = value; queue.push({state[dst], dst}); }
    }
  }
  return state;
}

inline std::size_t resident_rounds(const Adjacency &graph, std::vector<std::uint32_t> state,
                                 std::vector<std::uint32_t> active,
                                 const std::vector<std::uint32_t> &expected) {
  for (std::size_t round = 1; round <= 256; ++round) {
    auto next = state;
    for (auto source : active) {
      if (state[source] == inf) continue;
      for (const auto &[dst, weight] : graph[source]) {
        const auto value = std::uint64_t(state[source]) + weight;
        if (value >= 0x7ffffffeU) throw std::invalid_argument("fixture relaxation reaches routed infinity");
        next[dst] = std::min(next[dst], static_cast<std::uint32_t>(value));
      }
    }
    active.clear();
    for (std::size_t v = 0; v < state.size(); ++v)
      if (next[v] < state[v]) active.push_back(v);
    state = std::move(next);
    if (active.empty()) {
      if (state != expected) throw std::logic_error("resident relaxation differs from Dijkstra");
      return round;
    }
  }
  throw std::invalid_argument("fixture exceeds hardware superstep cap");
}
} // namespace routed_fixture
