#pragma once

#include "fixture.hpp"
#include "spine_sim/grasu_update/cached_processor.hpp"

namespace handoff_test {
constexpr auto kFullCache = grasu_update_detail::kCachedHotSegments;

// Padding belongs to an empty source row: it remains visible to both G and R.
inline void pad_cache(GraSuPmaLayout &layout, std::size_t padding_source) {
  require(layout.segments.size() < 2 * kFullCache, "cache fixture is already full");
  const auto [begin, end] = layout.row_slot_bounds.at(padding_source);
  require(begin == end, "padding source must not own live or reserved edges");
  const auto count = 2 * kFullCache;
  std::array<std::uint32_t, kGraSuSegmentSlots> blank;
  blank.fill(kGraSuPmaEmpty);
  const auto index = begin / kGraSuSegmentSlots;
  layout.segments.insert(layout.segments.begin() + index, count, blank);
  layout.reserved_segments.insert(layout.reserved_segments.begin() + index, count, blank);
  layout.binary_heads.insert(layout.binary_heads.begin() + index, count,
                            (static_cast<std::uint64_t>(padding_source) << 32) | kGraSuPmaEmpty);
  const auto slots = static_cast<std::uint32_t>(count * kGraSuSegmentSlots);
  for (std::size_t source = padding_source; source < layout.vertices; ++source) {
    auto &bounds = layout.row_slot_bounds[source];
    if (source != padding_source) bounds.first += slots;
    bounds.second += slots;
  }
}

inline Fixture cached_fixture(std::size_t vertices, bool cold_high_source, bool empty) {
  Fixture f{};
  f.vertices = vertices;
  const auto high = static_cast<std::uint32_t>((vertices - 1) / 65536 * 65536);
  require(high >= 65536, "cache fixture must exercise a high source ID");
  f.before = {{0, 1, 9}, {1, 32, 3}, {32, 64, 4}, {64, 65, 2},
              {0, high, 30}, {high, 5, 9}, {high, 65540, 11}};
  for (std::size_t p = 1; p * 65536 < vertices; ++p)
    f.before.push_back({0, static_cast<std::uint32_t>(p * 65536 + 1), 20});
  f.after = f.before;
  f.warm.primary = shortest_paths(vertices, f.before);
  f.physical_counts.resize((vertices + 65535) / 65536);
  if (!empty) {
    for (auto &edge : f.after) {
      if (!(edge.source == high || (edge.source == 0 &&
            (edge.destination == 1 || edge.destination == 65537)))) continue;
      auto deletion = edge;
      deletion.delete_op = true;
      f.updates.push_back(deletion);
      edge.weight = edge.source == high ? 2 : 4;
      f.updates.push_back(edge);
      f.physical_counts[edge.destination / 65536] += 2;
    }
    f.warm.active_vertices = {0, high};
  }
  f.expected = shortest_paths(vertices, f.after);
  auto reserved = f.updates;
  reserved.push_back({2, 3, 6});
  f.layout = GraSuPartitionedPmaLayout::build(vertices, 65536, f.before, reserved,
                                             GraSuPmaWordAbi::kWeightedFullWord);
  for (auto &layout : f.layout.partitions) pad_cache(layout, cold_high_source ? 10 : high + 1);
  require(edge_set(f.layout.live_edges()) == edge_set(f.before), "padding changed logical graph");
  return f;
}
} // namespace handoff_test
