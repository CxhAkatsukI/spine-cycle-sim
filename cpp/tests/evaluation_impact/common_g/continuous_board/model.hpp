#pragma once

#include "resident_state.hpp"

namespace continuous_g {
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
    return pack_lanes(physical, packed);
  }

  void advance(unsigned batch, const std::vector<BatchShard>& updates) {
    check_input(batch == next_batch++ && batch < 3, "resident batches must be applied in order");
    const auto canonical = pack_batch(batch);
    apply_physical(graph, expected, updates, canonical);
    for (unsigned i = ends[batch]; i < ends[batch + 1]; ++i)
      prepared_g::mutate(state, input.updates[i]);
    check_edge_set();
  }

  void check_edge_set() const {
    continuous_g::check_edge_set(graph, expected, state);
  }

  std::size_t check(const std::vector<Words>& observed) const {
    return check_words(observed, expected);
  }
};
}  // namespace continuous_g
