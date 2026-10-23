#pragma once

#include "input.hpp"
#include "../k4_config.hpp"
#include "../handoff/memory.hpp"
#include "../progress.hpp"
#include <iostream>

namespace warm_comparison {
inline void integrated(const Input& input, const std::filesystem::path& output,
                       std::uint64_t latency, bool reverse, std::uint64_t maximum) {
  Scheduler scheduler;
  const auto clock = scheduler.add_clock_mhz("core", 150);
  MockMemoryBackend backend("memory", clock, {32, latency, 1, 32, 32, true});
  scheduler.add_component(backend);
  handoff_test::Fixture fixture{};
  fixture.vertices = input.after.compact.vertices;
  fixture.before = input.before;
  fixture.after = input.after.edges;
  fixture.updates = input.updates;
  fixture.warm = input.after.initial;
  auto reservations = fixture.updates;
  // Routed R requires a physical source-0 row in every shard, even if empty.
  // Reserve it before G; the resident handoff must never inject graph storage.
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
  GraSuNativeConfig g_config;
  g_config.pma_word_abi = GraSuPmaWordAbi::kWeightedFullWord;
  g_config.cache_segments_per_half = 131072;
  // Preserve natural row geometry instead of padding this diagnostic to a
  // synthetic 16-MiB cache window; every edited segment is physically read/written.
  g_config.compact_parallel_search = g_config.compact_finite_search = true;
  g_config.compact_search_contexts = 64;
  g_config.compact_metadata_credits = 32;
  GraSuShardedPmaUpdateSystem g(scheduler, clock, backend, fixture.layout, fixture.updates, g_config,
                               kGraSuReGraphU55cChannelCapacityBytes);
  const auto plan = g.runtime_plan();
  for (std::size_t p = 0; p < fixture.layout.partitions.size(); ++p)
    initialize_grasu_pma_layout_payloads(backend, fixture.layout.partitions[p],
        handoff_test::shard_config(plan, p, g_config.cache_segments_per_half));
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
  const auto graph = handoff_test::graph_bytes(backend, layout, plan);
  auto config = ei::k4_configuration(ei::control("prefetch_gather_reuse"));
  config.reuse_resident_pma = true;
  config.compute.cache_segments_per_half = g_config.cache_segments_per_half;
  config.compute.runtime_physical_updates_per_shard = fixture.physical_counts;
  config.compute.vertex_state_base = config.compute.source_state_base = 0;
  config.compute.source_state_buffer_stride = input.after.compact.aligned_vertices * 4ull;
  config.status_address = config.compute.source_state_buffer_stride;
  RoutedReGraphSystem r(scheduler, clock, backend, layout, input.after.initial, config);
  require(handoff_test::same_placement(plan, r.runtime_plan()), "G/R placement mismatch");
  require(handoff_test::graph_bytes(backend, layout, plan) == graph &&
      backend.traffic_stats().reads.bytes == gt.reads.bytes &&
      backend.traffic_stats().writes.bytes == gt.writes.bytes, "R initialization rewrote PMA or injected traffic");
  r.register_components(reverse);
  for (std::uint64_t i = 0; i < maximum && !r.done() && !r.failed(); ++i) {
    scheduler.step(); r.advance_if_complete();
  }
  require(r.done() && !r.failed(), "R failed or exhausted cycle budget");
  require(r.encoded_state() == input.oracle.states.back() &&
      r.rounds().size() == input.oracle.states.size(), "R did not reach the common new-graph oracle");
  for (std::size_t i = 0; i < r.rounds().size(); ++i)
    require(r.rounds()[i].active_vertices == input.oracle.active[i], "R active trajectory mismatch");
  for (unsigned copy = 0; copy < 2; ++copy)
    require(r.source_state(copy, r.rounds().size() & 1U) == r.encoded_state(), "R final replica mismatch");
  require(handoff_test::graph_bytes(backend, layout, plan) == graph, "R modified resident PMA");
  const auto rc = r.counters();
  const auto rt = subtract_memory_traffic(backend.traffic_stats(), gt);
  require(rc.start_cycle >= gc.end_cycle && rc.axi_requests == rc.axi_completions &&
      rc.axi_beats == rc.axi_completed_beats && backend.outstanding() == 0 &&
      rc.live_edges == input.after.edges.size() * r.rounds().size() &&
      rc.packets * 8 == rc.live_edges + rc.dummy_edges &&
      rt.reads.bytes == (rc.extent_reads + rc.row_reads + rc.segment_reads + rc.source_lines + rc.apply_reads) * 64 &&
      rt.writes.bytes == (input.after.compact.aligned_vertices * 12ull + 4) * r.rounds().size(),
      "R physical ledger or non-overlap mismatch");
  ei::write_progress(r, output);
  ei::wt::write_words(output / "final.u32le", r.distances());
  std::cout << "WARM_RESULT {\"arm\":\"gr\",\"g_cycles\":" << gc.end_cycle - gc.start_cycle
      << ",\"r_cycles\":" << rc.end_cycle - rc.start_cycle << ",\"cycles\":" << rc.end_cycle - gc.start_cycle
      << ",\"handoff_cycle_gap\":" << rc.start_cycle - gc.end_cycle
      << ",\"rounds\":" << r.rounds().size() << ",\"g_read_bytes\":" << gt.reads.bytes
      << ",\"g_write_bytes\":" << gt.writes.bytes << ",\"read_bytes\":" << gt.reads.bytes + rt.reads.bytes
      << ",\"write_bytes\":" << gt.writes.bytes + rt.writes.bytes
      << ",\"physical_handoff\":true,\"correctness\":true,\"ledger_closed\":true}" << std::endl;
  r.unregister_components(); scheduler.remove_component(backend);
  require(scheduler.component_count() == 0, "G/R leaked scheduler components");
}
}  // namespace warm_comparison
