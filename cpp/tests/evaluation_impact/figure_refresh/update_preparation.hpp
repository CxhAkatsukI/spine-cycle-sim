#pragma once

#include "input.hpp"

namespace figure_refresh {
constexpr std::size_t kUpdatePartitionVertices = 65536;

inline GraSuPartitionedPmaLayout reserved_grasu(const wc::Input& input) {
  auto reservations = input.updates;
  for (std::size_t p = 0; p * kUpdatePartitionVertices < input.after.compact.vertices; ++p) {
    const auto owns_zero = [p](const auto& edge) {
      return edge.source == 0 && edge.destination / kUpdatePartitionVertices == p;
    };
    if (std::none_of(input.before.begin(), input.before.end(), owns_zero) &&
        std::none_of(input.updates.begin(), input.updates.end(), owns_zero))
      reservations.push_back({0, static_cast<std::uint32_t>(p * kUpdatePartitionVertices), 1, false});
  }
  return GraSuPartitionedPmaLayout::build(input.after.compact.vertices, kUpdatePartitionVertices,
      input.before, reservations, GraSuPmaWordAbi::kWeightedFullWord);
}

inline std::vector<GraSuEdge> grasu_batch(const wc::Input& input, std::size_t index,
                                        std::size_t count) {
  return {input.updates.begin() + index * input.updates.size() / count,
          input.updates.begin() + (index + 1) * input.updates.size() / count};
}

inline SpineEdgeSlice ordered_batch(const SpineEdgeSlice& trace, std::size_t index,
                                   std::size_t count) {
  const auto begin = trace.edges.begin() + index * trace.edges.size() / count;
  const auto end = trace.edges.begin() + (index + 1) * trace.edges.size() / count;
  SpineEdgeSlice batch{.vertices = trace.vertices, .edges = {begin, end},
                       .case_name = trace.case_name};
  std::stable_sort(batch.edges.begin(), batch.edges.end(), [](const auto& a, const auto& b) {
    return std::tie(a.src, a.dst, a.weight, a.diff) < std::tie(b.src, b.dst, b.weight, b.diff);
  });
  return batch;
}
} // namespace figure_refresh
