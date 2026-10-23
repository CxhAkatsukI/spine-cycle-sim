#pragma once

#include <algorithm>
#include <array>
#include <cstdint>
#include <stdexcept>
#include <tuple>
#include <vector>

#include "spine_sim/grasu.hpp"
#include "spine_sim/spine_l0.hpp"

namespace warm_host {
using namespace spine::sim;
inline constexpr std::uint32_t kPartitionVertices = 65536;

inline void validate(std::uint32_t vertices, const std::vector<GraSuEdge>& updates) {
  if (!vertices || vertices >= (std::uint32_t{1} << 31) || updates.empty())
    throw std::invalid_argument("nonempty insertion batch and representable vertex count required");
  for (const auto& edge : updates)
    if (edge.source >= vertices || edge.destination >= vertices || edge.delete_op ||
        !edge.weight || edge.weight > kGraSuPmaWeightMask)
      throw std::invalid_argument("batch outside common insertion ABI");
}

inline std::vector<std::uint8_t> prepare_spine(const std::vector<GraSuEdge>& updates) {
  std::vector<SpineEdgeRecord> sorted;
  sorted.reserve(updates.size());
  for (const auto& edge : updates) sorted.push_back({edge.source, edge.destination, edge.weight, 1});
  std::sort(sorted.begin(), sorted.end(), [](const auto& a, const auto& b) {
    return std::tie(a.src, a.dst) < std::tie(b.src, b.dst);
  });
  return encode_spine_sort_edges(sorted);
}

struct PreparedGraSu {
  std::vector<std::array<std::vector<std::uint64_t>, 4>> shards;
  std::vector<std::uint32_t> source_seeds;
};

inline PreparedGraSu prepare_grasu(std::uint32_t vertices, const std::vector<GraSuEdge>& updates) {
  PreparedGraSu result;
  result.shards.resize((std::uint64_t{vertices} + kPartitionVertices - 1) / kPartitionVertices);
  std::vector<std::size_t> counts(result.shards.size(), 0);
  result.source_seeds.reserve(updates.size());
  for (const auto& edge : updates) {
    const auto shard = edge.destination / kPartitionVertices;
    const auto lane = counts.at(shard)++ % 4;
    const auto word = (std::uint64_t{edge.source} << 32) |
        encode_grasu_pma_edge(edge.destination % kPartitionVertices, edge.weight);
    result.shards.at(shard).at(lane).push_back(word);
    result.source_seeds.push_back(edge.source);
  }
  // Native runtime buffers allocate at least one word per lane, including empty lanes.
  for (auto& shard : result.shards) for (auto& lane : shard) if (lane.empty()) lane.push_back(0);
  std::sort(result.source_seeds.begin(), result.source_seeds.end());
  result.source_seeds.erase(std::unique(result.source_seeds.begin(), result.source_seeds.end()),
                            result.source_seeds.end());
  return result;
}
}  // namespace warm_host
