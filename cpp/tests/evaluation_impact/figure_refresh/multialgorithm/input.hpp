#pragma once

#include "../input.hpp"
#include "spine_sim/spine_system.hpp"
#include <cmath>
#include <iostream>
#include <numeric>

namespace figure_refresh::multi {
struct Input {
  wc::Input graph;
  AlgorithmPolicyConfig algorithm;
  std::vector<std::uint32_t> old_degree, new_degree, expected_labels;
  std::vector<double> expected_rank;
  SpineResidualCorrectionPlan correction;
};

inline std::vector<std::uint32_t> labels(std::size_t vertices, const std::vector<GraSuEdge>& edges) {
  std::vector<std::uint32_t> parent(vertices);
  std::iota(parent.begin(), parent.end(), 0);
  const auto root = [&](std::uint32_t v) {
    while (parent[v] != v) { parent[v] = parent[parent[v]]; v = parent[v]; }
    return v;
  };
  for (const auto& e : edges) {
    const auto a = root(e.source), b = root(e.destination);
    parent[std::max(a, b)] = std::min(a, b);
  }
  for (auto& p : parent) p = root(p);
  return parent;
}

inline std::vector<double> pagerank(std::size_t vertices, const std::vector<GraSuEdge>& edges,
                                   const std::vector<std::uint32_t>& degree, float damping) {
  std::vector<double> rank(vertices, 1.0 / vertices), next(vertices);
  for (std::size_t iteration = 0; iteration < 1000; ++iteration) {
    double dangling = 0;
    for (std::size_t v = 0; v < vertices; ++v) if (!degree[v]) dangling += rank[v];
    std::fill(next.begin(), next.end(), (1.0 - double(damping) + double(damping) * dangling) / vertices);
    for (const auto& e : edges) next[e.destination] += double(damping) * rank[e.source] / degree[e.source];
    double error = 0;
    for (std::size_t v = 0; v < vertices; ++v) error += std::fabs(next[v] - rank[v]);
    rank.swap(next);
    if (error < 1e-12) return rank;
  }
  throw std::runtime_error("independent double-precision PageRank oracle did not converge");
}

inline Input load(const std::string& path, const std::string& updates, const std::string& algorithm) {
  Input result;
  require(algorithm == "CC" || algorithm == "ResPR", "unsupported multialgorithm workload");
  auto& g = result.graph;
  if (path == "smoke") {
    g.after.compact.vertices = 16;
    g.after.compact.aligned_vertices = 65536;
    for (std::uint32_t v = 0; v < 16; ++v)
      g.before.push_back({v, v / 8 * 8 + (v + 1) % 8, 1, false});
    for (const auto& e : std::vector<GraSuEdge>(g.before))
      if (algorithm == "CC") g.before.push_back({e.destination, e.source, 1, false});
    g.updates = {{0, 8, 1, false}};
    if (algorithm == "CC") g.updates.push_back({8, 0, 1, false});
    g.after.edges = g.before;
    g.after.edges.insert(g.after.edges.end(), g.updates.begin(), g.updates.end());
  } else g = figure_refresh::load(path, updates, 0, false);
  const auto vertices = g.after.compact.vertices;
  result.algorithm = {.kind = algorithm == "CC" ? GraphAlgorithmKind::kConnectedComponents :
      GraphAlgorithmKind::kResidualPageRank, .vertices = vertices, .epsilon = float(1e-5 / vertices),
      .residual_contract = ResidualPageRankContract::kHardwareWarmDanglingLinf};
  auto& initial = g.after.initial;
  initial.active_vertices.clear();
  for (const auto& e : g.updates) initial.active_vertices.push_back(e.source);
  std::sort(initial.active_vertices.begin(), initial.active_vertices.end());
  initial.active_vertices.erase(std::unique(initial.active_vertices.begin(), initial.active_vertices.end()),
                                initial.active_vertices.end());
  if (algorithm == "CC") {
    // Min-label propagation implements WCC only with reciprocal input.
    std::set<std::pair<std::uint32_t, std::uint32_t>> reciprocal;
    for (const auto& e : g.after.edges) reciprocal.emplace(e.source, e.destination);
    for (const auto& e : g.after.edges)
      require(reciprocal.contains({e.destination, e.source}), "CC requires reciprocal graph and batch");
    initial.primary = labels(vertices, g.before);
    result.expected_labels = labels(vertices, g.after.edges);
    return result;
  }
  result.old_degree.assign(vertices, 0);
  result.new_degree.assign(vertices, 0);
  for (const auto& e : g.before) ++result.old_degree[e.source];
  for (const auto& e : g.after.edges) ++result.new_degree[e.source];
  for (double rank : pagerank(vertices, g.before, result.old_degree, result.algorithm.damping))
    initial.primary.push_back(GraphAlgorithmPolicy::float_to_word(rank));
  result.expected_rank = pagerank(vertices, g.after.edges, result.new_degree, result.algorithm.damping);
  auto& c = result.correction;
  c.old_rank_words = initial.primary;
  c.old_out_degrees = result.old_degree;
  c.new_out_degrees = result.new_degree;
  c.touched_sources = initial.active_vertices;
  std::vector<bool> touched(vertices);
  for (auto v : c.touched_sources) touched[v] = true;
  std::vector<float> seed(vertices);
  const auto contribution = [&](const GraSuEdge& e, const auto& degree, float sign) {
    if (touched[e.source]) seed[e.destination] += sign * result.algorithm.damping *
        GraphAlgorithmPolicy::word_to_float(initial.primary[e.source]) / degree[e.source];
  };
  for (const auto& e : g.before) contribution(e, result.old_degree, -1);
  for (const auto& e : g.after.edges) contribution(e, result.new_degree, 1);
  float dangling_delta = 0;
  for (auto v : c.touched_sources) dangling_delta += result.algorithm.damping *
      GraphAlgorithmPolicy::word_to_float(initial.primary[v]) *
      (int(!result.new_degree[v]) - int(!result.old_degree[v])) / float(vertices);
  for (std::size_t v = 0; v < vertices; ++v) {
    seed[v] += dangling_delta;
    c.seed_words.push_back(GraphAlgorithmPolicy::float_to_word(seed[v]));
    if (std::fabs(seed[v]) > result.algorithm.epsilon) c.active_vertices.push_back(v);
  }
  initial.auxiliary.assign(vertices, 0);
  initial.active_vertices.clear();
  return result;
}

inline double validate_rank(const Input& input, const std::vector<std::uint32_t>& rank,
                            const std::vector<std::uint32_t>& residual) {
  require(rank.size() == input.expected_rank.size() && residual.size() == rank.size(), "PR state size mismatch");
  double maximum = 0, l1 = 0;
  for (std::size_t v = 0; v < rank.size(); ++v) {
    const double value = GraphAlgorithmPolicy::word_to_float(rank[v]);
    require(std::isfinite(value) && value >= 0 &&
        std::fabs(GraphAlgorithmPolicy::word_to_float(residual[v])) <= input.algorithm.epsilon,
        "PR invalid final rank or nonconverged residual");
    const auto error = std::fabs(value - input.expected_rank[v]);
    maximum = std::max(maximum, error);
    l1 += error;
  }
  const auto bound = rank.size() * double(input.algorithm.epsilon) / (1.0 - input.algorithm.damping);
  std::cout << "PR_ORACLE {\"maximum_error\":" << maximum << ",\"l1_error\":" << l1
      << ",\"l1_error_bound\":" << bound << "}" << std::endl;
  require(l1 <= bound,
          "PR final rank differs from independent fixed-point oracle beyond the residual error bound");
  return maximum;
}
} // namespace figure_refresh::multi
