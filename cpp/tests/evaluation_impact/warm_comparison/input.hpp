#pragma once

#include "../oracle.hpp"
#include "../handoff/fixture.hpp"

namespace warm_comparison {
namespace ei = evaluation_impact;
using namespace spine::sim;
using handoff_test::require;

inline std::vector<std::uint32_t> dijkstra(std::size_t vertices,
    const std::vector<GraSuEdge>& edges, std::uint32_t root) {
  std::vector<std::vector<std::pair<std::uint32_t, std::uint16_t>>> rows(vertices);
  for (const auto& edge : edges) rows.at(edge.source).emplace_back(edge.destination, edge.weight);
  using Item = std::pair<std::uint32_t, std::uint32_t>;
  std::priority_queue<Item, std::vector<Item>, std::greater<Item>> queue;
  std::vector<std::uint32_t> values(vertices, GraphAlgorithmPolicy::kSsspInfinity);
  values.at(root) = 0;
  queue.emplace(0, root);
  while (!queue.empty()) {
    const auto [distance, source] = queue.top(); queue.pop();
    if (values[source] != distance) continue;
    for (const auto& [destination, weight] : rows[source]) {
      const auto next = std::uint64_t{distance} + weight;
      require(next < GraphAlgorithmPolicy::kSsspInfinity, "Dijkstra overflow");
      if (next < values[destination]) {
        values[destination] = static_cast<std::uint32_t>(next);
        queue.emplace(next, destination);
      }
    }
  }
  return values;
}

struct Input {
  ei::st::Input after;
  std::vector<GraSuEdge> before, updates;
  std::uint32_t root{};
  ei::Oracle oracle;
};

inline void index(ei::st::Input& input) {
  auto& c = input.compact;
  std::sort(input.edges.begin(), input.edges.end(), [](const auto& a, const auto& b) {
    return std::tie(a.source, a.destination) < std::tie(b.source, b.destination);
  });
  c.offsets.assign(c.vertices + 1, 0);
  for (const auto& edge : input.edges) ++c.offsets.at(edge.source + 1);
  for (std::size_t v = 0; v < c.vertices; ++v) c.offsets[v + 1] += c.offsets[v];
  c.initial.assign(c.aligned_vertices, 0);
  for (std::size_t v = 0; v < c.vertices; ++v)
    c.initial[v] = input.initial.primary[v] == GraphAlgorithmPolicy::kSsspInfinity
        ? ei::rg::kSsspInfinity : input.initial.primary[v];
  for (const auto v : input.initial.active_vertices) c.initial.at(v) |= ei::rg::kSsspActive;
}

inline Input finish(ei::st::Input base, bool restore_weights) {
  require(base.initial.active_vertices.size() == 1, "one initial seed required");
  Input result;
  result.root = base.initial.active_vertices.front();
  if (restore_weights) for (auto& edge : base.edges) if (edge.source == result.root) {
    require(edge.weight <= 4079, "warm source-weight restoration overflows");
    edge.weight += 16;
  }
  result.before = base.edges;
  require(dijkstra(base.compact.vertices, result.before, result.root) == base.initial.primary,
          "input is not the independently converged old graph");
  std::set<std::uint32_t> existing;
  for (const auto& edge : result.before) if (edge.source == result.root) existing.insert(edge.destination);
  std::vector<std::uint32_t> targets;
  for (std::uint32_t v = 0; v < base.compact.vertices; ++v)
    if (v != result.root && !existing.contains(v) && base.initial.primary[v] > 3 &&
        base.initial.primary[v] != GraphAlgorithmPolicy::kSsspInfinity) targets.push_back(v);
  std::sort(targets.begin(), targets.end(), [&](auto a, auto b) {
    if (base.initial.primary[a] != base.initial.primary[b])
      return base.initial.primary[a] > base.initial.primary[b];
    return a < b;
  });
  require(targets.size() >= 3, "three distinct reachable shortcut destinations required");
  for (std::size_t i = 0; i < 3; ++i) {
    GraSuEdge update{result.root, targets[i], static_cast<std::uint16_t>(i + 1), false};
    result.updates.push_back(update);
    base.edges.push_back(update);
  }
  index(base);
  result.after = std::move(base);
  result.oracle = ei::closure(result.after, 128);
  const auto expected = dijkstra(result.after.compact.vertices, result.after.edges, result.root);
  for (std::size_t v = 0; v < expected.size(); ++v)
    require((result.oracle.states.back()[v] & ei::rg::kSsspValueMask) ==
        (expected[v] == GraphAlgorithmPolicy::kSsspInfinity ? ei::rg::kSsspInfinity : expected[v]),
        "new-graph independent Dijkstra mismatch");
  return result;
}

inline Input load(const std::string& directory) {
  if (directory != "smoke") return finish(ei::st::Input::load(directory), true);
  ei::st::Input base;
  base.compact.vertices = 96;
  base.compact.aligned_vertices = 65536;
  for (std::uint32_t v = 0; v < 95; ++v) base.edges.push_back({v, v + 1, 1, false});
  base.initial.primary = dijkstra(96, base.edges, 0);
  base.initial.active_vertices = {0};
  return finish(std::move(base), false);
}
}  // namespace warm_comparison
