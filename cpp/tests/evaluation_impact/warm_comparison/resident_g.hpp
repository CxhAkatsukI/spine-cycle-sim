#pragma once

#include "input.hpp"
#include "../handoff/memory.hpp"
#include <iostream>

namespace warm_comparison {
struct ResidentG {
  GraSuPartitionedPmaLayout layout;
  GraSuReGraphRuntimePlan plan;
  GraSuUpdateCounters counters;
  MemoryTrafficStats traffic;
  std::vector<std::size_t> physical_counts;
  std::vector<std::uint8_t> graph;
};

// Shared by every algorithm: maintenance finishes before the resident R handoff.
inline ResidentG resident_g(const Input& input, Scheduler& scheduler, ClockId clock,
                           MemoryBackend& backend, std::uint64_t maximum) {
  handoff_test::Fixture fixture{};
  fixture.vertices = input.after.compact.vertices;
  fixture.before = input.before;
  fixture.after = input.after.edges;
  fixture.updates = input.updates;
  fixture.warm = input.after.initial;
  auto reservations = fixture.updates;
  for (std::size_t p = 0; p * 65536 < fixture.vertices; ++p) {
    const auto owns_source_zero = [p](const auto& edge) {
      return edge.source == 0 && edge.destination / 65536 == p;
    };
    if (std::none_of(fixture.before.begin(), fixture.before.end(), owns_source_zero) &&
        std::none_of(fixture.updates.begin(), fixture.updates.end(), owns_source_zero))
      reservations.push_back({0, static_cast<std::uint32_t>(p * 65536), 1, false});
  }
  fixture.layout = GraSuPartitionedPmaLayout::build(fixture.vertices, 65536, fixture.before,
      reservations, GraSuPmaWordAbi::kWeightedFullWord);
  fixture.physical_counts.resize(fixture.layout.partitions.size());
  for (const auto& edge : fixture.updates) ++fixture.physical_counts.at(edge.destination / 65536);
  GraSuNativeConfig config;
  config.pma_word_abi = GraSuPmaWordAbi::kWeightedFullWord;
  config.cache_segments_per_half = 131072;
  config.compact_parallel_search = config.compact_finite_search = true;
  config.compact_search_contexts = 64;
  config.compact_metadata_credits = 32;
  GraSuShardedPmaUpdateSystem g(scheduler, clock, backend, fixture.layout, fixture.updates, config,
                               kGraSuReGraphU55cChannelCapacityBytes);
  const auto plan = g.runtime_plan();
  for (std::size_t p = 0; p < fixture.layout.partitions.size(); ++p)
    initialize_grasu_pma_layout_payloads(backend, fixture.layout.partitions[p],
        handoff_test::shard_config(plan, p, config.cache_segments_per_half));
  g.register_components();
  for (std::uint64_t i = 0; i < maximum && !g.done() && !g.failed(); ++i) {
    scheduler.step(); g.advance_if_complete();
  }
  require(g.done() && !g.failed() && backend.outstanding() == 0, "G failed or exhausted cycle budget");
  require(handoff_test::edge_set(g.live_edges()) == handoff_test::edge_set(fixture.after),
          "G graph does not match the declared batch");
  const auto layout = g.materialized_partitioned_layout();
  const auto expected = handoff_test::edited_layout(fixture);
  for (std::size_t p = 0; p < layout.partitions.size(); ++p)
    require(layout.partitions[p].segments == expected.partitions[p].segments &&
        layout.partitions[p].row_slot_bounds == fixture.layout.partitions[p].row_slot_bounds,
        "G physical PMA differs from independent edit oracle");
  const auto gc = g.counters();
  const auto gt = backend.traffic_stats();
  require(gc.updates == input.updates.size() &&
      gt.reads.bytes == gc.update_read_bytes + gc.row_read_bytes + gc.binary_read_bytes + gc.pma_read_bytes &&
      gt.writes.bytes == gc.pma_write_bytes, "G physical byte ledger mismatch");
  std::cout << "WARM_STAGE {\"stage\":\"G\",\"cycles\":" << gc.end_cycle - gc.start_cycle << "}" << std::endl;
  g.unregister_components();
  return {layout, plan, gc, gt, fixture.physical_counts, handoff_test::graph_bytes(backend, layout, plan)};
}
} // namespace warm_comparison
