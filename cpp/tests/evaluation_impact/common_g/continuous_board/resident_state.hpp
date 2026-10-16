#pragma once

#include "host_prepared/input.hpp"
#include "host/weighted_pma_update_reference.hpp"

namespace continuous_g {
namespace host = grasu::integration;
using prepared_g::check_input;
constexpr unsigned kCacheSegments = 131072;
using Words = std::array<std::vector<std::uint32_t>, 4>;

struct BatchShard {
  std::vector<std::uint64_t> physical;
  std::array<std::vector<std::uint64_t>, 4> lanes;
  std::array<unsigned, 4> counts{};
};

inline std::vector<BatchShard> pack_lanes(const std::vector<std::vector<unsigned long>>& physical,
    const std::vector<host::WeightedPmaPackedShardBuffers>& packed) {
  check_input(physical.size() == packed.size(), "physical update shard count changed");
  std::vector<BatchShard> result(physical.size());
  for (unsigned shard = 0; shard < result.size(); ++shard) {
    auto& target = result[shard];
    target.physical.assign(physical[shard].begin(), physical[shard].end());
    for (unsigned i = 0; i < target.physical.size(); ++i)
      target.lanes[i % 4].push_back(target.physical[i]);
    for (unsigned lane = 0; lane < 4; ++lane) {
      target.counts[lane] = target.lanes[lane].size();
      if (target.lanes[lane].empty()) target.lanes[lane].push_back(0);
      check_input(target.lanes[lane].size() <= packed[shard].updates[lane].size(),
                  "batch exceeds reserved update buffer");
    }
  }
  return result;
}

inline void apply_physical(const host::WeightedPartitionedPmaGraph& graph,
    std::vector<Words>& expected, const std::vector<BatchShard>& updates,
    const std::vector<BatchShard>& canonical) {
  check_input(updates.size() == canonical.size(), "batch shard count changed");
  for (unsigned shard = 0; shard < updates.size(); ++shard) {
    check_input(updates[shard].physical == canonical[shard].physical &&
                updates[shard].lanes == canonical[shard].lanes &&
                updates[shard].counts == canonical[shard].counts, "batch packing changed");
    for (auto raw : updates[shard].physical) {
      const auto segment = host::weighted_pma_update_segment(graph.shards[shard], raw);
      const auto [port, offset] = host::weighted_pma_segment_port(segment, kCacheSegments);
      auto begin = expected[shard][port].begin() + offset;
      auto end = begin + host::kWeightedPmaSegmentSlots;
      const auto word = static_cast<std::uint32_t>(raw);
      auto found = std::lower_bound(begin, end, word);
      if (raw & host::kWeightedPmaDelete) {
        check_input(found != end && *found == word, "physical deletion absent");
        std::rotate(found, found + 1, end);
        *(end - 1) = host::kWeightedPmaEmpty;
      } else {
        check_input(*(end - 1) == host::kWeightedPmaEmpty, "physical segment overflow");
        std::move_backward(found, end - 1, end);
        *found = word;
      }
    }
  }
}

inline void check_edge_set(const host::WeightedPartitionedPmaGraph& graph,
    const std::vector<Words>& expected, const prepared_g::State& state) {
  prepared_g::State decoded;
  for (unsigned shard = 0; shard < graph.shards.size(); ++shard) {
    const auto& descriptor = graph.shards[shard];
    for (unsigned src = 0; src < graph.vertices; ++src) {
      const auto bounds = descriptor.row_bounds.at(src);
      for (unsigned slot = bounds >> 32; slot < static_cast<std::uint32_t>(bounds); ++slot) {
        const auto [port, offset] = host::weighted_pma_segment_port(slot / 16, kCacheSegments);
        const auto word = expected.at(shard).at(port).at(offset + slot % 16);
        if (word == host::kWeightedPmaEmpty) continue;
        const auto dst = descriptor.destination_base + (word & ((1U << 19) - 1));
        check_input(dst < graph.vertices && word >> 19, "decoded PMA endpoint/weight invalid");
        check_input(decoded.emplace(std::make_pair(graph.internal_to_external.at(src),
            graph.internal_to_external.at(dst)), word >> 19).second, "decoded duplicate edge");
      }
    }
  }
  check_input(decoded == state, "physical PMA differs from independent external edge-set oracle");
}

inline std::size_t check_words(const std::vector<Words>& observed, const std::vector<Words>& expected) {
  check_input(observed == expected, "complete resident PMA/padding mismatch");
  std::size_t words = 0;
  for (const auto& shard : observed) for (const auto& port : shard) words += port.size();
  return words;
}
}  // namespace continuous_g
