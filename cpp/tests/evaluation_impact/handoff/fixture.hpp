#pragma once

#include "spine_sim/routed_regraph.hpp"

#include <algorithm>
#include <queue>
#include <set>
#include <stdexcept>
#include <tuple>

namespace handoff_test {
using namespace spine::sim;
constexpr auto kInf = GraphAlgorithmPolicy::kSsspInfinity;

inline void require(bool value, const char *message) {
  if (!value) throw std::runtime_error(message);
}

inline std::vector<std::uint32_t> shortest_paths(std::size_t vertices,
                                                const std::vector<GraSuEdge> &edges) {
  std::vector<std::vector<std::pair<std::uint32_t, std::uint16_t>>> rows(vertices);
  for (const auto &edge : edges) rows.at(edge.source).emplace_back(edge.destination, edge.weight);
  std::vector<std::uint32_t> state(vertices, kInf);
  using Item = std::pair<std::uint32_t, std::uint32_t>;
  std::priority_queue<Item, std::vector<Item>, std::greater<Item>> work;
  state[0] = 0;
  work.emplace(0, 0);
  while (!work.empty()) {
    const auto [distance, source] = work.top();
    work.pop();
    if (distance != state[source]) continue;
    for (const auto &[destination, weight] : rows[source])
      if (distance + weight < state[destination]) {
        state[destination] = distance + weight;
        work.emplace(state[destination], destination);
      }
  }
  return state;
}

struct Fixture {
  std::size_t vertices;
  std::vector<GraSuEdge> before, after, updates;
  GraSuPartitionedPmaLayout layout;
  AlgorithmInitialState warm;
  std::vector<std::uint32_t> expected;
  std::vector<std::size_t> physical_counts;
};

inline GraSuPartitionedPmaLayout edited_layout(const Fixture &f) {
  auto result = f.layout;
  for (const auto &update : f.updates) {
    auto &part = result.partitions[result.partition_for_destination(update.destination)];
    auto &segment = part.segments[part.segment_for(update)];
    const auto word = encode_grasu_pma_edge(part.local_destination(update.destination), update.weight);
    const auto position = std::lower_bound(segment.begin(), segment.end(), word);
    if (update.delete_op) {
      require(position != segment.end() && *position == word, "oracle deletion is not live");
      std::move(position + 1, segment.end(), position);
      segment.back() = kGraSuPmaEmpty;
    } else {
      require(position != segment.end() && *position != word && segment.back() == kGraSuPmaEmpty,
              "oracle insertion has no distinct reservation");
      std::move_backward(position, segment.end() - 1, segment.end());
      *position = word;
    }
  }
  return result;
}

inline Fixture fixture(std::size_t vertices, bool empty) {
  Fixture f{};
  f.vertices = vertices;
  f.before = {{0, 1, 9}, {1, 32, 3}, {32, 64, 4}, {64, 65, 2}};
  for (std::size_t partition = 1; partition * 65536 < vertices; ++partition)
    f.before.push_back({0, static_cast<std::uint32_t>(partition * 65536 + 1), 20});
  f.after = f.before;
  f.warm.primary = shortest_paths(vertices, f.before);
  f.physical_counts.resize((vertices + 65535) / 65536);
  if (!empty) {
    for (auto &edge : f.after) {
      if (edge.source != 0 || edge.destination >= 131072) continue;
      auto deletion = edge;
      deletion.delete_op = true;
      f.updates.push_back(deletion);
      edge.weight = edge.destination == 1 ? 2 : 4;
      f.updates.push_back(edge);
      f.physical_counts[edge.destination / 65536] += 2;
    }
    f.warm.active_vertices = {0};
  }
  f.expected = shortest_paths(vertices, f.after);
  // An unused reservation must survive the G->R boundary, not be compacted out.
  auto reserved = f.updates;
  reserved.push_back({2, 3, 6});
  f.layout = GraSuPartitionedPmaLayout::build(vertices, 65536, f.before, reserved,
                                             GraSuPmaWordAbi::kWeightedFullWord);
  return f;
}

inline std::set<std::tuple<std::uint32_t, std::uint32_t, std::uint16_t>>
edge_set(const std::vector<GraSuEdge> &edges) {
  std::set<std::tuple<std::uint32_t, std::uint32_t, std::uint16_t>> result;
  for (const auto &edge : edges) result.emplace(edge.source, edge.destination, edge.weight);
  return result;
}
} // namespace handoff_test
