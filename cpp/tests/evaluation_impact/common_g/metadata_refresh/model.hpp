#pragma once

#include "native_geometry/layout.hpp"
#include "continuous_board/resident_state.hpp"

namespace metadata_g {
namespace cg = continuous_g;

struct Model : native_g::Layout {
  std::vector<cg::Words> expected;
  prepared_g::State state;
  unsigned generation = 0, next_batch = 0;

  Model() {
    // Return to the initial edge set through device operations before remapping.
    // No host PMA upload/reset is permitted between generations.
    for (unsigned batch : {1u, 2u}) {
      auto& edits = batches[batch];
      edits.erase(std::remove_if(edits.begin(), edits.end(), [](const auto& edge) {
        return edge.source == 2 || edge.source == 3 || edge.source == 262144 || edge.source == 262145;
      }), edits.end());
    }
    for (auto& edge : batches[2]) edge.weight = 7;
    for (const auto& shard : packed) expected.push_back(shard.pma_words);
    for (unsigned source = 0; source < native_g::kVertices; ++source)
      for (unsigned destination : {0u, native_g::kVertices - 1})
        prepared_g::mutate(state, {source, destination, 7, false});
    cg::check_edge_set(graph, expected, state);
  }

  void remap() {
    cg::check_input(generation == 0 && next_batch == 3, "metadata remap out of order");
    std::vector<cg::Words> initial;
    for (const auto& shard : packed) initial.push_back(shard.pma_words);
    cg::check_words(expected, initial);
    for (unsigned shard = 0; shard < graph.shards.size(); ++shard) {
      auto& layout = graph.shards[shard];
      if (shard == 0 || shard == 4) {
        for (unsigned source = 0; source < 4; ++source) {
          const unsigned other = source + 262144;
          std::swap(layout.row_bounds[source], layout.row_bounds[other]);
          for (unsigned mapped : {source, other}) {
            const auto bounds = layout.row_bounds[mapped];
            for (unsigned segment = (bounds >> 32) / 16;
                 segment < static_cast<std::uint32_t>(bounds) / 16; ++segment)
              layout.binary_heads[segment] = (std::uint64_t(mapped) << 32) |
                  static_cast<std::uint32_t>(layout.binary_heads[segment]);
          }
        }
      }
      std::copy(layout.row_bounds.begin(), layout.row_bounds.end(), packed[shard].row_bounds.begin());
      std::copy(layout.binary_heads.begin(), layout.binary_heads.end(), packed[shard].binary_heads.begin());
    }
    generation = 1;
    next_batch = 0;
    cg::check_edge_set(graph, expected, state);
  }

  std::vector<cg::BatchShard> pack_batch(unsigned batch) const {
    cg::check_input(batch < 3, "metadata batch outside declared matrix");
    std::vector<std::vector<unsigned long>> physical(graph.shards.size());
    std::array<unsigned, 4> ports{};
    for (const auto& edge : batches[batch]) {
      const auto shard = edge.destination / native_g::kPartitionVertices;
      physical[shard].push_back(native_g::host::pack_weighted_update(edge.source,
          native_g::host::encode_weighted_pma_word(edge.destination % native_g::kPartitionVertices,
                                                  edge.weight), edge.delete_op));
      const auto segment = native_g::host::weighted_pma_update_segment(graph.shards[shard], physical[shard].back());
      ++ports[native_g::host::weighted_pma_segment_port(segment, native_g::kCacheSegments).first];
    }
    cg::check_input(ports == (batch ? std::array<unsigned, 4>{4, 2, 4, 2} : std::array<unsigned, 4>{}),
                    "metadata remap lost full hot/cold port coverage");
    return cg::pack_lanes(physical, packed);
  }

  void advance(unsigned batch, const std::vector<cg::BatchShard>& updates) {
    cg::check_input(batch == next_batch++ && batch < 3, "metadata batch order changed");
    cg::apply_physical(graph, expected, updates, pack_batch(batch));
    for (const auto& edge : batches[batch]) prepared_g::mutate(state, edge);
    cg::check_edge_set(graph, expected, state);
  }
};
}  // namespace metadata_g
