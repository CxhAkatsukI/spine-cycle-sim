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

struct Fixture {
  static constexpr std::uint32_t kVertices = 161, kPartition = 64;
  std::vector<Batch> batches;
  std::vector<std::size_t> maximum_updates;

  explicit Fixture(const std::string &name) {
    require(name == "staggered" || name == "all-active", "unknown lifecycle input");
    std::vector<GraSuEdge> initial, reservation;
    std::array<std::vector<GraSuEdge>, 3> updates;
    for (std::uint32_t shard = 0; shard < 3; ++shard) {
      for (std::uint32_t source = 0; source < 32; ++source) {
        for (std::uint32_t dst = 0; dst < 24; ++dst)
          initial.push_back({source, shard * kPartition + dst, 3});
        const GraSuEdge old{source, shard * kPartition + source % 24, 3, true};
        const GraSuEdge first{old.source, old.destination, 1};
        const GraSuEdge second{old.source, old.destination, 5};
        if (name == "all-active" || shard != 2) {
          updates[0].push_back(old);
          updates[0].push_back(first);
          auto remove = first;
          remove.delete_op = true;
          updates[2].push_back(remove);
        } else updates[2].push_back(old);
        updates[2].push_back(second);
      }
    }
    for (const auto &batch : updates) reservation.insert(reservation.end(), batch.begin(), batch.end());
    auto current = GraSuPartitionedPmaLayout::build(kVertices, kPartition, initial, reservation,
                                                   GraSuPmaWordAbi::kWeightedFullWord);
    for (auto &part : current.partitions) {
      std::array<std::uint32_t, 16> empty;
      empty.fill(kGraSuPmaEmpty);
      part.segments.resize(2 * kCache, empty);
      part.reserved_segments.resize(2 * kCache, empty);
      part.binary_heads.resize(2 * kCache, static_cast<std::uint64_t>(kVertices - 1) << 32 | kGraSuPmaEmpty);
      part.row_slot_bounds.back().second = 2 * kCache * 16;
    }
    using Key = std::tuple<std::uint32_t, std::uint32_t, std::uint16_t>;
    std::set<Key> oracle;
    for (const auto &edge : initial) oracle.emplace(edge.source, edge.destination, edge.weight);
    maximum_updates.resize(3);
    for (const auto &sequence : updates) {
      Batch batch{current, current, sequence, std::vector<std::vector<GraSuEdge>>(3)};
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
      for (std::size_t shard = 0; shard < 3; ++shard) {
        maximum_updates[shard] = std::max(maximum_updates[shard], batch.by_shard[shard].size());
        require(batch.initial.partitions[shard].row_slot_bounds == batch.expected.partitions[shard].row_slot_bounds &&
                    batch.initial.partitions[shard].binary_heads == batch.expected.partitions[shard].binary_heads,
                "lifecycle unexpectedly requires new reservation metadata");
      }
      current = batch.expected;
      batches.push_back(std::move(batch));
    }
  }
};
} // namespace sharded_g_test::lifecycle
