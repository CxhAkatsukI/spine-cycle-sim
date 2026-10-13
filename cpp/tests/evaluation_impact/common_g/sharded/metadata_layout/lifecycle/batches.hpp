#pragma once

#include "../../fixture.hpp"

#include <set>
#include <tuple>

namespace sharded_g_test::lifecycle {
struct Batch {
  GraSuPartitionedPmaLayout initial, expected;
  std::vector<GraSuEdge> updates;
  std::vector<std::vector<GraSuEdge>> by_shard;
  std::size_t probes{}, multi_segment_updates{};
  std::size_t touched() const {
    return std::count_if(by_shard.begin(), by_shard.end(), [](const auto &u) { return !u.empty(); });
  }
};

inline std::vector<Batch> make_fixed_batches(GraSuPartitionedPmaLayout current,
    const std::vector<GraSuEdge> &initial, const std::vector<std::vector<GraSuEdge>> &sequences,
    std::vector<std::size_t> &maximum_updates) {
  using Key = std::tuple<std::uint32_t, std::uint32_t, std::uint16_t>;
  std::set<Key> oracle;
  for (const auto &edge : initial)
    require(!edge.delete_op && oracle.emplace(edge.source, edge.destination, edge.weight).second,
            "resident initial edge set differs");
  maximum_updates.assign(current.partitions.size(), 0);
  std::vector<Batch> batches;
  for (const auto &sequence : sequences) {
    Batch batch{current, current, sequence, std::vector<std::vector<GraSuEdge>>(current.partitions.size())};
    for (const auto &edge : sequence) {
      const auto shard = current.partition_for_destination(edge.destination);
      batch.by_shard[shard].push_back(edge);
      auto &part = batch.expected.partitions[shard];
      const auto index = part.segment_for(edge);
      auto &segment = part.segments[index];
      const auto word = encode_grasu_pma_edge(part.local_destination(edge.destination), edge.weight);
      const auto position = std::lower_bound(segment.begin(), segment.end(), word);
      const Key key{edge.source, edge.destination, edge.weight};
      if (edge.delete_op) {
        require(oracle.erase(key) == 1 && position != segment.end() && *position == word,
                "lifecycle delete is not live");
        std::move(position + 1, segment.end(), position);
        segment.back() = kGraSuPmaEmpty;
      } else {
        require(oracle.insert(key).second && position != segment.end() && *position != word &&
                    segment.back() == kGraSuPmaEmpty, "lifecycle insert is duplicate or unreserved");
        std::move_backward(position, segment.end() - 1, segment.end());
        *position = word;
      }
      const auto [start, stop] = part.row_slot_bounds[edge.source];
      std::size_t begin = start / 16, end = stop / 16, mid = (begin + end) / 2;
      batch.multi_segment_updates += end - begin > 1;
      const auto target = static_cast<std::uint64_t>(edge.source) << 32 | word;
      while (begin != mid) {
        ++batch.probes;
        if (part.binary_heads[mid] <= target) begin = mid;
        else end = mid;
        mid = (begin + end) / 2;
      }
      require(begin == index, "lifecycle independent search differs");
    }
    std::set<Key> observed;
    for (const auto &edge : batch.expected.live_edges()) observed.emplace(edge.source, edge.destination, edge.weight);
    require(observed == oracle, "lifecycle full edge-set oracle differs");
    for (std::size_t shard = 0; shard < current.partitions.size(); ++shard) {
      maximum_updates[shard] = std::max(maximum_updates[shard], batch.by_shard[shard].size());
      require(batch.initial.partitions[shard].row_slot_bounds == batch.expected.partitions[shard].row_slot_bounds &&
                  batch.initial.partitions[shard].binary_heads == batch.expected.partitions[shard].binary_heads,
              "lifecycle unexpectedly requires new reservation metadata");
    }
    current = batch.expected;
    batches.push_back(std::move(batch));
  }
  return batches;
}
} // namespace sharded_g_test::lifecycle
