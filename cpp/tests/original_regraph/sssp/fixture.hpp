#pragma once

#include "../frontend_wiring.hpp"
#include "spine_sim/routed_regraph.hpp"

namespace original_regraph_sssp_test {
namespace rg = spine::sim::original_regraph;
using original_regraph_frontend_test::require;
inline constexpr std::size_t kVertices = 129;
inline constexpr std::size_t kPadded = 65536;

struct Fixture {
  std::vector<spine::sim::GraSuEdge> edges;
  spine::sim::AlgorithmInitialState initial;
  std::vector<std::uint32_t> encoded;
  std::vector<std::uint32_t> expected;
  std::vector<std::vector<rg::EdgeBurst>> compact;
};

inline Fixture fixture(bool warm, bool inactive) {
  Fixture f;
  f.edges = {{0, 1, 2, false}, {0, 32, 2, false}, {1, 2, 3, false},
             {32, 64, 3, false}, {64, 128, 4, false}, {32, 1, 1, false},
             {64, 1, 7, false}, {0, 128, 9, false}, {128, 0, 11, false}};
  f.initial.primary.assign(kVertices, spine::sim::GraphAlgorithmPolicy::kSsspInfinity);
  f.initial.primary[0] = 0;
  if (warm) {
    f.initial.primary[1] = 5;
    f.initial.primary[32] = 17;
    f.initial.primary[64] = 42;
    f.initial.active_vertices = {0, 32, 64};
  } else f.initial.active_vertices = {0};
  if (inactive) f.initial.active_vertices.clear();
  f.encoded.assign(kPadded, 0);
  for (std::size_t v = 0; v < kVertices; ++v)
    f.encoded[v] = f.initial.primary[v] == spine::sim::GraphAlgorithmPolicy::kSsspInfinity
        ? rg::kSsspInfinity : f.initial.primary[v];
  for (const auto v : f.initial.active_vertices) f.encoded[v] |= rg::kSsspActive;

  // Independent synchronous relaxation; no production UDF helper in the oracle.
  f.expected = f.encoded;
  for (auto& word : f.expected) word &= 0x7fffffffu;
  for (const auto edge : f.edges) {
    const auto source = f.encoded[edge.source];
    if (!(source & 0x80000000u) || (source & 0x7fffffffu) == 0x7ffffffeu) continue;
    const auto update = (source & 0x7fffffffu) + edge.weight;
    auto& destination = f.expected[edge.destination];
    if (update < (destination & 0x7fffffffu)) destination = update | 0x80000000u;
  }
  f.compact.resize(4);
  std::array<std::vector<rg::Edge>, 4> paths;
  for (const auto edge : f.edges)
    paths[edge.source % 4].push_back({edge.source, edge.destination | (edge.weight << 19)});
  for (std::size_t path = 0; path < 4; ++path) {
    auto& edges = paths[path];
    std::stable_sort(edges.begin(), edges.end(), [](auto a, auto b) { return a.source < b.source; });
    const auto padded = std::max<std::size_t>(8, (edges.size() + 7) / 8 * 8);
    edges.resize(padded, {rg::kSsspActive, rg::kSsspActive});
    for (std::size_t offset = 0; offset < edges.size(); offset += 8) {
      rg::EdgeBurst burst;
      std::copy_n(edges.begin() + offset, 8, burst.begin());
      f.compact[path].push_back(burst);
    }
  }
  return f;
}
}  // namespace original_regraph_sssp_test
