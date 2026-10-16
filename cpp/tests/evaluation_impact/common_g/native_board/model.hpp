#pragma once

#include "native_geometry/layout.hpp"
#include "continuous_board/resident_state.hpp"

namespace native_board_g {
struct Model : native_g::Layout {
  std::vector<continuous_g::Words> expected;
  prepared_g::State state;
  std::array<unsigned, 4> ends{0, 0, 20, 40};
  unsigned next_batch = 0;

  Model() {
    for (const auto& shard : packed) expected.push_back(shard.pma_words);
    for (unsigned source = 0; source < native_g::kVertices; ++source)
      for (unsigned destination : {0u, native_g::kVertices - 1})
        prepared_g::mutate(state, {source, destination, 7, false});
    continuous_g::check_edge_set(graph, expected, state);
  }

  std::vector<continuous_g::BatchShard> pack_batch(unsigned batch) const {
    prepared_g::check_input(batch < 3, "native batch index outside declared matrix");
    auto result = continuous_g::pack_lanes(lower(batch), packed);
    std::array<unsigned, 4> ports{};
    for (unsigned shard = 0; shard < result.size(); ++shard)
      for (auto raw : result[shard].physical) {
        const auto segment = native_g::host::weighted_pma_update_segment(graph.shards[shard], raw);
        const auto port = native_g::host::weighted_pma_segment_port(segment, native_g::kCacheSegments).first;
        ++ports.at(port);
      }
    prepared_g::check_input(ports == (batch ? std::array<unsigned, 4>{6, 4, 6, 4}
                                           : std::array<unsigned, 4>{}), "native hot/cold coverage changed");
    return result;
  }

  void advance(unsigned batch, const std::vector<continuous_g::BatchShard>& updates) {
    prepared_g::check_input(batch == next_batch++ && batch < 3, "native resident batches must remain ordered");
    continuous_g::apply_physical(graph, expected, updates, pack_batch(batch));
    for (const auto& edge : batches.at(batch)) prepared_g::mutate(state, edge);
    continuous_g::check_edge_set(graph, expected, state);
  }

  std::size_t check(const std::vector<continuous_g::Words>& observed) const {
    return continuous_g::check_words(observed, expected);
  }
};
}  // namespace native_board_g
