#pragma once

#include "batches.hpp"

namespace sharded_g_test::lifecycle {
struct Fixture {
  static constexpr std::uint32_t kVertices = 161, kPartition = 64;
  std::vector<Batch> batches;
  std::vector<std::size_t> maximum_updates;

  explicit Fixture(const std::string &name) {
    require(name == "staggered" || name == "all-active", "unknown lifecycle input");
    std::vector<GraSuEdge> initial, reservation;
    std::vector<std::vector<GraSuEdge>> updates(3);
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
    batches = make_fixed_batches(std::move(current), initial, updates, maximum_updates);
  }
};
} // namespace sharded_g_test::lifecycle
