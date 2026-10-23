#pragma once

#include "../warm_comparison/input.hpp"
#include "spine_sim/spine_l0.hpp"

namespace figure_refresh {
namespace wc = warm_comparison;
using namespace spine::sim;
using handoff_test::require;

inline wc::Input load(const std::string& graph, const std::string& updates,
                      std::uint32_t root, bool propagation) {
  if (graph == "smoke") return wc::load("smoke");
  const auto before = load_spine_edge_slice(graph);
  const auto batch = load_spine_edge_slice(updates);
  require(before.vertices == batch.vertices && root < before.vertices, "invalid input vertex domain");
  wc::Input input;
  input.root = root;
  input.after.compact.vertices = before.vertices;
  input.after.compact.aligned_vertices = (before.vertices + 65535) / 65536 * 65536;
  std::set<std::pair<std::uint32_t, std::uint32_t>> keys;
  for (const auto& edge : before.edges) {
    require(edge.diff == 1 && keys.emplace(edge.src, edge.dst).second,
            "initial graph must have unique positive edges");
    input.before.push_back({edge.src, edge.dst, edge.weight, false});
  }
  input.after.edges = input.before;
  for (const auto& edge : batch.edges) {
    require(edge.diff == 1 && keys.emplace(edge.src, edge.dst).second,
            "this registered matrix admits fresh insertions only");
    GraSuEdge update{edge.src, edge.dst, edge.weight, false};
    input.updates.push_back(update);
    input.after.edges.push_back(update);
    input.after.initial.active_vertices.push_back(edge.src);
  }
  auto& active = input.after.initial.active_vertices;
  std::sort(active.begin(), active.end());
  active.erase(std::unique(active.begin(), active.end()), active.end());
  // Setup and the independent old-graph oracle are outside device time.
  if (propagation) {
    input.after.initial.primary = wc::dijkstra(before.vertices, input.before, root);
    wc::index(input.after);
    input.oracle = wc::ei::closure(input.after, 128);
    const auto expected = wc::dijkstra(before.vertices, input.after.edges, root);
    for (std::size_t v = 0; v < expected.size(); ++v)
      require((input.oracle.states.back()[v] & wc::ei::rg::kSsspValueMask) ==
          (expected[v] == GraphAlgorithmPolicy::kSsspInfinity ? wc::ei::rg::kSsspInfinity : expected[v]),
          "independent post-update shortest-path oracle mismatch");
  }
  return input;
}

inline SpineL0Config spine_config() {
  SpineL0Config config;
  config.maintenance_architecture = SpineMaintenanceArchitecture::kCandidate10OnePass;
  config.segmented_fallback = true;
  config.reader_active_record_control_cycles = 520;
  config.segmented_fallback_setup_cycles = 3185887;
  return config;
}

inline SpineEdgeSlice slice(const wc::Input& input, bool batch) {
  SpineEdgeSlice result{.vertices = input.after.compact.vertices, .edges = {}, .case_name = "figure_refresh"};
  for (const auto& edge : batch ? input.updates : input.before)
    result.edges.push_back({edge.source, edge.destination, edge.weight, 1});
  return result;
}
} // namespace figure_refresh
