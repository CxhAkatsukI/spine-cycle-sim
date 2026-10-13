#pragma once

#include "fixture.hpp"
#include "spine_sim/spine_l0.hpp"

#include <set>
#include <tuple>

namespace sharded_g_test {
struct RealFixture {
  std::size_t vertices{}, live_edges{}, probes{}, multi_segment_updates{};
  GraSuPartitionedPmaLayout initial, expected;
  std::vector<GraSuEdge> updates;
  std::vector<std::vector<GraSuEdge>> by_shard;

  RealFixture(const std::string &graph_path, const std::string &update_path) {
    const auto graph = load_spine_edge_slice(graph_path);
    const auto batch = load_spine_edge_slice(update_path);
    require(graph.vertices == batch.vertices && graph.vertices < 65535,
            "real input must share one destination shard");
    // An isolated final source owns only cache-footprint padding, never edits.
    vertices = graph.vertices + 1;
    live_edges = graph.edges.size();
    std::vector<GraSuEdge> before;
    using Key = std::tuple<std::uint32_t, std::uint32_t, std::uint16_t>;
    std::set<Key> oracle;
    for (const auto &edge : graph.edges) {
      require(edge.diff == 1 && oracle.emplace(edge.src, edge.dst, edge.weight).second,
              "initial graph is not a distinct positive edge set");
      before.push_back({edge.src, edge.dst, edge.weight});
    }
    for (const auto &edge : batch.edges) {
      require(edge.diff == 1 || edge.diff == -1, "update is not a unit mutation");
      updates.push_back({edge.src, edge.dst, edge.weight, edge.diff == -1});
    }
    initial = GraSuPartitionedPmaLayout::build(vertices, 65536, before, updates,
                                               GraSuPmaWordAbi::kWeightedFullWord);
    require(initial.partitions.size() == 1, "real input unexpectedly spans shards");
    auto &part = initial.partitions[0];
    require(part.segments.size() <= 2 * kCache, "real input exceeds the declared hot footprint");
    std::array<std::uint32_t, 16> empty;
    empty.fill(kGraSuPmaEmpty);
    part.segments.resize(2 * kCache, empty);
    part.reserved_segments.resize(2 * kCache, empty);
    part.binary_heads.resize(2 * kCache, static_cast<std::uint64_t>(vertices - 1) << 32 | kGraSuPmaEmpty);
    part.row_slot_bounds.back().second = 2 * kCache * 16;
    expected = initial;
    by_shard = {updates};
    for (const auto &update : updates) {
      const auto segment_index = part.segment_for(update);
      auto &segment = expected.partitions[0].segments.at(segment_index);
      const auto word = encode_grasu_pma_edge(update.destination, update.weight);
      const auto position = std::lower_bound(segment.begin(), segment.end(), word);
      const Key key{update.source, update.destination, update.weight};
      if (update.delete_op) {
        require(oracle.erase(key) == 1 && position != segment.end() && *position == word,
                "real delete is not live in both oracles");
        std::move(position + 1, segment.end(), position);
        segment.back() = kGraSuPmaEmpty;
      } else {
        require(oracle.insert(key).second && position != segment.end() &&
                    *position != word && segment.back() == kGraSuPmaEmpty,
                "real insertion is duplicate or unreserved");
        std::move_backward(position, segment.end() - 1, segment.end());
        *position = word;
      }
      const auto [begin_slot, end_slot] = part.row_slot_bounds[update.source];
      std::size_t begin = begin_slot / 16, end = end_slot / 16, mid = (begin + end) / 2;
      multi_segment_updates += end - begin > 1;
      const auto target = static_cast<std::uint64_t>(update.source) << 32 | word;
      while (begin != mid) {
        ++probes;
        if (part.binary_heads[mid] <= target) begin = mid;
        else end = mid;
        mid = (begin + end) / 2;
      }
      require(begin == segment_index, "independent search-count oracle differs");
    }
    std::set<Key> materialized;
    for (const auto &edge : expected.partitions[0].live_edges())
      require(materialized.emplace(edge.source, edge.destination, edge.weight).second,
              "expected PMA has duplicate edges");
    require(materialized == oracle && probes > 0 && multi_segment_updates > 0,
            "real input lacks search coverage or disagrees with edge-set oracle");
  }

  std::size_t touched() const { return updates.empty() ? 0 : 1; }
};
} // namespace sharded_g_test
