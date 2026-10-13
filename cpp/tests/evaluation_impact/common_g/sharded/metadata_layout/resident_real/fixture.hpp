#pragma once

#include "../lifecycle/batches.hpp"
#include "../../ordered_input.hpp"

namespace sharded_g_test::resident_real {
struct Fixture {
  static constexpr std::uint32_t kPartition = 8192;
  std::size_t vertices{};
  std::vector<lifecycle::Batch> batches;
  std::vector<std::size_t> maximum_updates;

  Fixture(const std::string &graph_path, const std::string &updates_path) {
    const auto graph = load_ordered_g_slice(graph_path);
    const auto full = load_ordered_g_slice(updates_path);
    require(graph.vertices == full.vertices && graph.edges.size() == 8192 && full.edges.size() == 65536,
            "resident chronological input dimensions differ");
    vertices = graph.vertices + 1;
    std::vector<GraSuEdge> initial, reservation;
    for (const auto &edge : graph.edges) {
      require(edge.diff == 1, "resident chronological initial edge is not positive");
      initial.push_back({edge.src, edge.dst, edge.weight});
    }
    for (const auto &edge : full.edges) {
      require(edge.diff == 1, "resident chronological batch is not insert-only");
      reservation.push_back({edge.src, edge.dst, edge.weight});
    }
    auto current = GraSuPartitionedPmaLayout::build(vertices, kPartition, initial, reservation,
                                                   GraSuPmaWordAbi::kWeightedFullWord);
    require(current.partitions.size() >= 2 && current.partitions.size() <= 3,
            "resident chronological fixture must have two or three shards");
    for (auto &part : current.partitions) {
      require(part.segments.size() <= 2 * kCache, "resident chronological reservation exceeds hot footprint");
      std::array<std::uint32_t, 16> empty;
      empty.fill(kGraSuPmaEmpty);
      part.segments.resize(2 * kCache, empty);
      part.reserved_segments.resize(2 * kCache, empty);
      part.binary_heads.resize(2 * kCache, static_cast<std::uint64_t>(vertices - 1) << 32 | kGraSuPmaEmpty);
      part.row_slot_bounds.back().second = 2 * kCache * 16;
    }
    std::vector<std::vector<GraSuEdge>> sequences(3);
    sequences[0].assign(reservation.begin(), reservation.begin() + 4096);
    sequences[2].assign(reservation.begin() + 4096, reservation.end());
    batches = lifecycle::make_fixed_batches(std::move(current), initial, sequences, maximum_updates);
  }
};
} // namespace sharded_g_test::resident_real
