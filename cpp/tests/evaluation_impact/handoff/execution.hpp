#pragma once

#include "memory.hpp"

#include <iostream>

namespace handoff_test {
struct Result {
  std::uint64_t g_cycles, r_cycles, reads, writes;
  std::size_t rounds;
  bool operator==(const Result &) const = default;
};

struct Observation {
  Result timing;
  GraSuUpdateCounters update;
};

inline Observation execute(const Fixture &f, GraSuNativeConfig g_config, bool reverse) {
  const auto cache = g_config.cache_segments_per_half;
  Scheduler scheduler;
  const auto clock = scheduler.add_clock_mhz("handoff-correctness", 150);
  MockMemoryBackend backend("memory", clock, {32, 7, 1, 16, 32, true});
  scheduler.add_component(backend);
  GraSuShardedPmaUpdateSystem g(scheduler, clock, backend, f.layout, f.updates, g_config,
                                kGraSuReGraphU55cChannelCapacityBytes);
  const auto plan = g.runtime_plan();
  // Cold graph allocation is outside both windows, including untouched shards.
  for (std::size_t p = 0; p < f.layout.partitions.size(); ++p) {
    const auto config = shard_config(plan, p, cache);
    if (g_config.compact_finite_search) require(config.row_channels != config.binary_channels,
                        "finite handoff did not exercise independent metadata banks");
    initialize_grasu_pma_layout_payloads(backend, f.layout.partitions[p], config);
  }
  g.register_components();
  // Full-cache tests transfer both 8-MiB halves of every updated shard.
  const std::uint64_t g_limit = g_config.compact_cached_hot ? 4000000 : 1000000;
  for (std::uint64_t step = 0; step < g_limit && !g.done() && !g.failed(); ++step) {
    scheduler.step();
    g.advance_if_complete();
  }
  if (!g.done() || g.failed() || backend.outstanding() != 0) {
    const auto c = g.counters();
    throw std::runtime_error("G did not drain: " + g.failure() + " cycles=" + std::to_string(c.end_cycle) +
        " updates=" + std::to_string(c.updates) + " cache=" + std::to_string(c.cache_updates) +
        " pma_reads=" + std::to_string(c.pma_reads) + " pma_writes=" + std::to_string(c.pma_writes) +
        " outstanding=" + std::to_string(backend.outstanding()));
  }
  require(edge_set(g.live_edges()) == edge_set(f.after), "G post-batch graph mismatch");
  const auto updated = g.materialized_partitioned_layout();
  const auto expected_layout = edited_layout(f);
  for (std::size_t p = 0; p < updated.partitions.size(); ++p) {
    require(updated.partitions[p].row_slot_bounds == f.layout.partitions[p].row_slot_bounds &&
                updated.partitions[p].segments.size() == f.layout.partitions[p].segments.size(),
                "G changed reserved PMA geometry");
    require(updated.partitions[p].segments == expected_layout.partitions[p].segments,
                "G complete physical PMA state differs from the functional edit oracle");
  }
  const auto g_counters = g.counters();
  require(g_counters.updates == f.updates.size(), "G physical-operation count mismatch");
  const auto g_traffic = backend.traffic_stats();
  require(g_traffic.reads.bytes == g_counters.update_read_bytes + g_counters.row_read_bytes +
              g_counters.binary_read_bytes + g_counters.pma_read_bytes &&
              g_traffic.writes.bytes == g_counters.pma_write_bytes, "G byte ledger is not conserved");
  g.unregister_components();
  const auto graph_before = graph_bytes(backend, updated, plan);
  const auto traffic_before = backend.traffic_stats();
  RoutedReGraphConfig config;
  config.reuse_resident_pma = true;
  config.compute.cache_segments_per_half = cache;
  config.compute.runtime_physical_updates_per_shard = f.physical_counts;
  RoutedReGraphSystem r(scheduler, clock, backend, updated, f.warm, config);
  require(same_placement(plan, r.runtime_plan()), "G/R runtime addresses differ");
  require(graph_bytes(backend, updated, plan) == graph_before, "R constructor rewrote G PMA");
  require(backend.traffic_stats().reads.bytes == traffic_before.reads.bytes &&
              backend.traffic_stats().writes.bytes == traffic_before.writes.bytes,
              "handoff injected hidden device traffic");
  r.register_components(reverse);
  for (std::uint64_t step = 0; step < 20000000 && !r.done() && !r.failed(); ++step) {
    scheduler.step();
    r.advance_if_complete();
  }
  require(r.done() && !r.failed(), "R handoff convergence failed");
  require(r.distances() == f.expected, "warm G->R differs from independent new-graph Dijkstra");
  require(graph_bytes(backend, updated, plan) == graph_before, "R changed G PMA during compute");
  const auto c = r.counters();
  const auto traffic = subtract_memory_traffic(backend.traffic_stats(), traffic_before);
  require(c.start_cycle >= g_counters.end_cycle && c.axi_requests == c.axi_completions &&
              c.axi_beats == c.axi_completed_beats && backend.outstanding() == 0,
              "G/R windows overlap or R requests remain");
  require(c.live_edges == f.after.size() * r.rounds().size() && r.rounds().back().active_vertices == 0,
              "R did not scan the updated graph to quiescence");
  const auto final_buffer = r.rounds().size() % 2;
  for (std::size_t copy = 0; copy < 2; ++copy)
    require(r.source_state(copy, final_buffer) == r.encoded_state(), "final source replica mismatch");
  Result result{g_counters.end_cycle - g_counters.start_cycle, c.end_cycle - c.start_cycle,
                traffic.reads.bytes, traffic.writes.bytes, r.rounds().size()};
  r.unregister_components();
  scheduler.remove_component(backend);
  require(scheduler.component_count() == 0, "handoff leaked scheduler components");
  return {result, g_counters};
}

inline Result run(std::size_t vertices, std::size_t cache, bool empty, bool reverse,
                  bool finite = false) {
  GraSuNativeConfig config;
  config.pma_word_abi = GraSuPmaWordAbi::kWeightedFullWord;
  config.cache_segments_per_half = cache;
  if (finite) {
    config.compact_parallel_search = true;
    config.compact_finite_search = true;
    config.compact_search_contexts = 64;
    config.compact_metadata_credits = 32;
  }
  const auto result = execute(fixture(vertices, empty), config, reverse).timing;
  std::cout << (finite ? "BANKED_HANDOFF_RESULT " : "HANDOFF_RESULT ")
            << "{\"vertices\":" << vertices << ",\"cache_segments\":" << cache
            << ",\"empty\":" << (empty ? "true" : "false") << ",\"reverse\":" << (reverse ? "true" : "false")
            << ",\"g_cycles\":" << result.g_cycles << ",\"r_cycles\":" << result.r_cycles
            << ",\"rounds\":" << result.rounds << ",\"r_read_bytes\":" << result.reads
            << ",\"r_write_bytes\":" << result.writes
            << ",\"physical_handoff_pass\":true,\"performance_admitted\":false}\n";
  return result;
}
} // namespace handoff_test
