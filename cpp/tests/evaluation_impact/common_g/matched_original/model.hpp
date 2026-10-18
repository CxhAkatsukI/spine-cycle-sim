#pragma once

#include "original_g_board/model.hpp"
#include "continuous_board/resident_state.hpp"
#include <numeric>

namespace matched_g {
namespace original = original_g_board;
namespace host = grasu::integration;
using original::require;

// A constant weight preserves destination ordering and every original segment.
inline std::uint64_t weighted(std::uint64_t edge) {
  return edge | (std::uint64_t{1} << 19);
}

inline std::uint32_t slot_word(std::uint64_t edge) {
  return edge == original::empty_edge ? host::kWeightedPmaEmpty
                                     : static_cast<std::uint32_t>(weighted(edge));
}

struct Model {
  original::Input input;
  host::WeightedPartitionedPmaGraph graph;
  host::WeightedPmaRuntimePlan plan;
  std::vector<host::WeightedPmaPackedShardBuffers> packed;
  std::vector<continuous_g::Words> expected;
  std::array<unsigned, 4> route_updates{};
  bool advanced = false;

  explicit Model(const char* path) : input(original::load(path)) {
    original::Longs rows;
    {
      const original::Model independent(input);
      rows = independent.rows;
      route_updates = independent.route_updates;
    }
    graph.vertices = input.vertices;
    graph.partition_vertices = input.vertices;
    graph.external_to_internal.resize(input.vertices);
    std::iota(graph.external_to_internal.begin(), graph.external_to_internal.end(), 0);
    graph.internal_to_external = graph.external_to_internal;
    graph.shards.resize(1);
    auto& shard = graph.shards.front();
    shard.source_vertices = shard.destination_vertices = input.vertices;
    shard.destination_base = 0;
    shard.row_bounds.assign(rows.begin(), rows.end());
    for (auto edge : input.binary) shard.binary_heads.push_back(weighted(edge));
    for (auto edge : input.prepared) shard.initial_pma_words.push_back(slot_word(edge));
    for (auto edge : input.updates) shard.physical_updates.push_back(weighted(edge));
    // Positive-size BOs are required even when no logical segment is present.
    if (!input.segments) {
      shard.binary_heads.push_back(0);
      shard.initial_pma_words.assign(16, host::kWeightedPmaEmpty);
    }
    plan = host::build_weighted_pma_runtime_plan(graph, continuous_g::kCacheSegments, 23,
        host::kU55cHbmPseudoChannelBytes, host::WeightedPmaChannelPolicy::lane_aware_u55c, true);
    packed = host::pack_weighted_pma_runtime_buffers(graph, plan);
    expected.push_back(packed.front().pma_words);
    check_logical(input.prepared);
    for (unsigned i = 0; i < input.updates.size(); ++i) {
      const auto edge = input.updates[i] & ~original::empty_edge;
      const auto source = edge >> 32;
      const auto first = input.binary.begin() + input.offsets[source] / 16;
      const auto last = input.binary.begin() + input.offsets[source + 1] / 16;
      const auto segment = std::upper_bound(first, last, edge) - input.binary.begin() - 1;
      require(host::weighted_pma_update_segment(shard, shard.physical_updates[i]) ==
                  static_cast<std::size_t>(segment), "matched G segment routing changed");
    }
  }

  std::vector<continuous_g::BatchShard> pack_batch() const {
    return continuous_g::pack_lanes({graph.shards.front().physical_updates}, packed);
  }

  void advance(const std::vector<continuous_g::BatchShard>& batch) {
    require(!advanced, "matched G batch already applied");
    continuous_g::apply_physical(graph, expected, batch, pack_batch());
    check_logical(input.final_state);
    advanced = true;
  }

  void check_logical(const original::Longs& logical) const {
    require(logical.size() == input.prepared.size(), "matched G logical extent changed");
    for (unsigned slot = 0; slot < logical.size(); ++slot) {
      const auto [port, offset] = host::weighted_pma_segment_port(slot / 16, continuous_g::kCacheSegments);
      require(expected.at(0).at(port).at(offset + slot % 16) == slot_word(logical[slot]),
              "matched G independent logical slot mismatch");
    }
  }

  std::size_t check(const std::vector<continuous_g::Words>& observed) const {
    return continuous_g::check_words(observed, expected);
  }
};
}  // namespace matched_g
