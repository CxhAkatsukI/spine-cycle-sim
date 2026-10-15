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

struct Model {
  prepared_g::Input input;
  host::WeightedPartitionedPmaGraph graph;
  host::WeightedPmaRuntimePlan plan;
  std::vector<host::WeightedPmaPackedShardBuffers> packed;
  std::vector<Words> expected;
  prepared_g::State state;
  std::array<unsigned, 4> ends;
  unsigned next_batch = 0;

  explicit Model(const char* path, bool warm_decrease_control = false) : input(path, warm_decrease_control),
      graph(host::build_weighted_partitioned_pma_graph(input.vertices,
          input.partition_vertices, input.initial, input.updates)),
      plan(host::build_weighted_pma_runtime_plan(graph, kCacheSegments, 23,
          host::kU55cHbmPseudoChannelBytes, host::WeightedPmaChannelPolicy::lane_aware_u55c, true)),
      packed(host::pack_weighted_pma_runtime_buffers(graph, plan)),
      ends{0, 0, unsigned(input.updates.size() / 2), unsigned(input.updates.size())} {
    check_input(input.partition_vertices == 65536, "board scope requires native 65536-vertex partitions");
    prepared_g::check_host_mapping(input, graph);
    for (const auto& shard : packed) expected.push_back(shard.pma_words);
    for (const auto& edge : input.initial) prepared_g::mutate(state, edge);
    check_edge_set();
  }

  std::vector<BatchShard> pack_batch(unsigned batch) const {
    check_input(batch < 3, "batch index outside declared matrix");
    const auto physical = prepared_g::batches(input, graph, ends[batch], ends[batch + 1]);
    std::vector<BatchShard> result(graph.shards.size());
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

  void advance(unsigned batch, const std::vector<BatchShard>& updates) {
    check_input(batch == next_batch++ && batch < 3, "resident batches must be applied in order");
    const auto canonical = pack_batch(batch);
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
    for (unsigned i = ends[batch]; i < ends[batch + 1]; ++i)
      prepared_g::mutate(state, input.updates[i]);
    check_edge_set();
  }

  void check_edge_set() const {
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

  std::size_t check(const std::vector<Words>& observed) const {
    check_input(observed == expected, "complete resident PMA/padding mismatch");
    std::size_t words = 0;
    for (const auto& shard : observed) for (const auto& port : shard) words += port.size();
    return words;
  }
};
}  // namespace continuous_g
