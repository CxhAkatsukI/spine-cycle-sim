#include "spine_sim/spine_l0.hpp"

#include <algorithm>
#include <limits>
#include <stdexcept>
#include <tuple>
#include <vector>

using namespace spine::sim;

namespace {
void require(bool condition, const char *message) {
  if (!condition) throw std::runtime_error(message);
}

auto records(const SpineL0State &state, const SpineL0Config &config,
             std::size_t minimum_level) {
  std::vector<std::tuple<std::uint32_t, std::uint32_t, std::uint16_t,
                         std::int32_t>> result;
  for (const bool hot : {false, true}) {
    const auto &families = hot ? state.hot_levels : state.cold_levels;
    for (const auto &levels : families) {
      for (std::size_t level = 0; level < config.levels; ++level) {
        require(level >= minimum_level || levels[level].empty(),
                "bootstrap occupied a reserved carry level");
        require(levels[level].size() <=
                    spine_level_layout(config, hot, level).edge_capacity,
                "bootstrap exceeded finite per-level capacity");
        for (const auto &edge : levels[level])
          result.emplace_back(edge.src, edge.dst, edge.weight, edge.diff);
      }
    }
  }
  std::sort(result.begin(), result.end());
  return result;
}
} // namespace

int main() {
  SpineL0Config base;
  base.max_sort_edges = 8;
  base.max_vertices = 256;
  base.vertex_partition_size = 256;
  SpineEdgeSlice snapshot{
      .vertices = 256, .edges = {}, .case_name = "reserved-carry-headroom"};
  for (std::uint32_t index = 0; index < 1022; ++index) {
    snapshot.edges.push_back({.src = index % 128, .dst = index % 16,
        .weight = static_cast<std::uint16_t>(index / 128 + 1), .diff = 1});
  }

  auto implicit_config = base;
  auto explicit_config = base;
  SpineResidentClassification old_classification, explicit_classification;
  const auto implicit_state = preload_spine_resident_snapshot(
      snapshot, implicit_config, &old_classification);
  const auto explicit_state = preload_spine_resident_snapshot(
      snapshot, explicit_config, &explicit_classification, 2);
  require(implicit_state.cold_levels == explicit_state.cold_levels &&
              implicit_state.hot_levels == explicit_state.hot_levels &&
              implicit_state.hot_vertices == explicit_state.hot_vertices &&
              implicit_config.hot_vertices == explicit_config.hot_vertices,
          "default resident placement changed");
  require(old_classification.family_edge_capacity == 1022 &&
              explicit_classification.family_edge_capacity == 1022 &&
              old_classification.hot_vertices.empty() &&
              !implicit_state.cold_levels[0][2].empty(),
          "test no longer exercises occupied low-level bootstrap");

  auto reserved_config = base;
  SpineResidentClassification reserved;
  const auto reserved_state = preload_spine_resident_snapshot(
      snapshot, reserved_config, &reserved, 4);
  require(reserved.family_edge_capacity == 1016 &&
              reserved.cold_partition_target == 1016 &&
              reserved.hot_shard_edge_capacity == 1016 &&
              reserved.automatic_hot_promotion &&
              !reserved.hot_vertices.empty(),
          "reserved levels were not deducted from classification capacity");
  require(records(implicit_state, implicit_config, 2) ==
              records(reserved_state, reserved_config, 4),
          "reserving carry headroom changed the physical record multiset");

  auto hub = snapshot;
  for (auto &edge : hub.edges) edge.dst = 0;
  auto hub_config = base;
  (void)preload_spine_resident_snapshot(hub, hub_config);
  bool capacity_rejected = false;
  hub_config = base;
  try {
    (void)preload_spine_resident_snapshot(hub, hub_config, nullptr, 4);
  } catch (const std::overflow_error &) {
    capacity_rejected = true;
  }
  require(capacity_rejected, "reserved bootstrap invented extra capacity");

  for (const std::size_t invalid : {std::size_t{0}, std::size_t{1},
           std::size_t{11}, std::numeric_limits<std::size_t>::max()}) {
    bool rejected = false;
    auto config = base;
    try {
      (void)preload_spine_resident_snapshot(snapshot, config, nullptr, invalid);
    } catch (const std::invalid_argument &) {
      rejected = true;
    }
    require(rejected && config.hot_vertices.empty(),
            "invalid bootstrap level accepted or mutated caller configuration");
  }
}
