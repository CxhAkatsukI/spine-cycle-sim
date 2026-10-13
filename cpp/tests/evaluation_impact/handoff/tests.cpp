#include "memory.hpp"

#include <iostream>

namespace ht = handoff_test;
using namespace spine::sim;

namespace {
struct Result {
  std::uint64_t g_cycles, r_cycles, reads, writes;
  std::size_t rounds;
  bool operator==(const Result &) const = default;
};

Result run(std::size_t vertices, std::size_t cache, bool empty, bool reverse) {
  const auto f = ht::fixture(vertices, empty);
  Scheduler scheduler;
  const auto clock = scheduler.add_clock_mhz("handoff-correctness", 150);
  MockMemoryBackend backend("memory", clock, {32, 7, 1, 16, 32, true});
  scheduler.add_component(backend);
  GraSuNativeConfig g_config;
  g_config.pma_word_abi = GraSuPmaWordAbi::kWeightedFullWord;
  g_config.cache_segments_per_half = cache;
  GraSuShardedPmaUpdateSystem g(scheduler, clock, backend, f.layout, f.updates, g_config,
                                kGraSuReGraphU55cChannelCapacityBytes);
  const auto plan = g.runtime_plan();
  // Cold graph allocation is outside both windows, including untouched shards.
  for (std::size_t p = 0; p < f.layout.partitions.size(); ++p)
    initialize_grasu_pma_layout_payloads(backend, f.layout.partitions[p], ht::shard_config(plan, p, cache));
  g.register_components();
  for (std::uint64_t step = 0; step < 1000000 && !g.done() && !g.failed(); ++step) {
    scheduler.step();
    g.advance_if_complete();
  }
  ht::require(g.done() && !g.failed() && backend.outstanding() == 0, "G did not drain before handoff");
  ht::require(ht::edge_set(g.live_edges()) == ht::edge_set(f.after), "G post-batch graph mismatch");
  const auto updated = g.materialized_partitioned_layout();
  for (std::size_t p = 0; p < updated.partitions.size(); ++p)
    ht::require(updated.partitions[p].row_slot_bounds == f.layout.partitions[p].row_slot_bounds &&
                updated.partitions[p].segments.size() == f.layout.partitions[p].segments.size(),
                "G changed reserved PMA geometry");
  const auto g_counters = g.counters();
  ht::require(g_counters.updates == f.updates.size(), "G physical-operation count mismatch");
  g.unregister_components();
  const auto graph_before = ht::graph_bytes(backend, updated, plan);
  const auto traffic_before = backend.traffic_stats();
  RoutedReGraphConfig config;
  config.reuse_resident_pma = true;
  config.compute.cache_segments_per_half = cache;
  config.compute.runtime_physical_updates_per_shard = f.physical_counts;
  RoutedReGraphSystem r(scheduler, clock, backend, updated, f.warm, config);
  ht::require(ht::same_placement(plan, r.runtime_plan()), "G/R runtime addresses differ");
  ht::require(ht::graph_bytes(backend, updated, plan) == graph_before, "R constructor rewrote G PMA");
  ht::require(backend.traffic_stats().reads.bytes == traffic_before.reads.bytes &&
              backend.traffic_stats().writes.bytes == traffic_before.writes.bytes,
              "handoff injected hidden device traffic");
  r.register_components(reverse);
  for (std::uint64_t step = 0; step < 20000000 && !r.done() && !r.failed(); ++step) {
    scheduler.step();
    r.advance_if_complete();
  }
  ht::require(r.done() && !r.failed(), "R handoff convergence failed");
  ht::require(r.distances() == f.expected, "warm G->R differs from independent new-graph Dijkstra");
  ht::require(ht::graph_bytes(backend, updated, plan) == graph_before, "R changed G PMA during compute");
  const auto c = r.counters();
  const auto traffic = subtract_memory_traffic(backend.traffic_stats(), traffic_before);
  ht::require(c.start_cycle >= g_counters.end_cycle && c.axi_requests == c.axi_completions &&
              c.axi_beats == c.axi_completed_beats && backend.outstanding() == 0,
              "G/R windows overlap or R requests remain");
  ht::require(c.live_edges == f.after.size() * r.rounds().size() && r.rounds().back().active_vertices == 0,
              "R did not scan the updated graph to quiescence");
  const auto final_buffer = r.rounds().size() % 2;
  for (std::size_t copy = 0; copy < 2; ++copy)
    ht::require(r.source_state(copy, final_buffer) == r.encoded_state(), "final source replica mismatch");
  Result result{g_counters.end_cycle - g_counters.start_cycle, c.end_cycle - c.start_cycle,
                traffic.reads.bytes, traffic.writes.bytes, r.rounds().size()};
  std::cout << "HANDOFF_RESULT {\"vertices\":" << vertices << ",\"cache_segments\":" << cache
            << ",\"empty\":" << (empty ? "true" : "false") << ",\"reverse\":" << (reverse ? "true" : "false")
            << ",\"g_cycles\":" << result.g_cycles << ",\"r_cycles\":" << result.r_cycles
            << ",\"rounds\":" << result.rounds << ",\"r_read_bytes\":" << result.reads
            << ",\"r_write_bytes\":" << result.writes
            << ",\"physical_handoff_pass\":true,\"performance_admitted\":false}\n";
  r.unregister_components();
  scheduler.remove_component(backend);
  ht::require(scheduler.component_count() == 0, "handoff leaked scheduler components");
  return result;
}

void rejection_tests() {
  const std::array<const char *, 7> labels{"row", "segment", "extent", "source0-reservation",
      "placement", "inflight", "missing-row"};
  for (unsigned kind = 0; kind < labels.size(); ++kind) {
    auto f = ht::fixture(129, false);
    Scheduler scheduler;
    const auto clock = scheduler.add_clock_mhz("reject", 150);
    MockMemoryBackend backend("memory", clock, {32, 7, 1, 16, 32, false});
    const auto plan = build_grasu_regraph_runtime_plan(f.layout, f.physical_counts, 1);
    auto native = ht::shard_config(plan, 0, 1);
    if (kind != 6) initialize_grasu_pma_layout_payloads(backend, f.layout.partitions[0], native);
    else backend.initialize_payload(native.pma_channels[0], native.pma_bases[0], std::vector<std::uint8_t>(64, 0xff));
    if (kind == 0) backend.initialize_payload(native.row_channels[0], native.row_offset_base, {1});
    if (kind == 1) backend.initialize_payload(native.pma_channels[0], native.pma_bases[0], {0});
    if (kind == 2) {
      backend.initialize_payload(native.row_channels[0], native.row_offset_base + f.vertices * 8, {0});
    }
    if (kind == 3) {
      f.before.erase(f.before.begin());
      f.layout = GraSuPartitionedPmaLayout::build(f.vertices, 65536, f.before, {}, GraSuPmaWordAbi::kWeightedFullWord);
    }
    const auto bytes = backend.inspect_payload(native.pma_channels[0], native.pma_bases[0], 64);
    RoutedReGraphConfig config;
    config.reuse_resident_pma = true;
    config.compute.cache_segments_per_half = 1;
    config.compute.runtime_physical_updates_per_shard = f.physical_counts;
    if (kind == 4) config.compute.runtime_physical_updates_per_shard = {32768};
    if (kind == 5) {
      backend.register_initiator(999);
      ht::require(backend.try_submit({.initiator_id = 999, .request_id = 1,
          .channel = native.row_channels[0], .operation = MemoryOperation::kRead,
          .address = native.row_offset_base, .bytes = 8, .write_data = {}}), "inflight fixture rejected");
      ht::require(backend.outstanding() != 0, "inflight fixture has no pending request");
    }
    const auto traffic_before = backend.traffic_stats();
    bool rejected = false;
    std::string reason;
    try { RoutedReGraphSystem r(scheduler, clock, backend, f.layout, f.warm, config); }
    catch (const std::exception &error) { rejected = true; reason = error.what(); }
    ht::require(rejected, "invalid resident handoff admitted");
    ht::require(backend.inspect_payload(native.pma_channels[0], native.pma_bases[0], 64) == bytes,
                "rejected resident handoff repaired or rewrote memory");
    ht::require(backend.traffic_stats().reads.requests == traffic_before.reads.requests &&
                backend.traffic_stats().writes.requests == traffic_before.writes.requests,
                "rejected handoff issued traffic");
    std::cout << "HANDOFF_REJECTION {\"case\":\"" << labels[kind] << "\",\"rejected\":true}\n";
    std::cout << "REJECTION_REASON " << labels[kind] << ": " << reason << '\n';
  }
  std::cout << "PASS: seven resident payload/extent/reservation/placement/drain rejections\n";
}
} // namespace

int main() {
  try {
    for (auto [vertices, cache, empty] : {std::tuple{129U, 1U, false},
        std::tuple{65569U, 1U, false}, std::tuple{131105U, 8U, false}, std::tuple{65569U, 1U, true}}) {
      const auto forward = run(vertices, cache, empty, false);
      ht::require(forward == run(vertices, cache, empty, true), "handoff cycles/state/traffic depend on registration order");
    }
    rejection_tests();
  } catch (const std::exception &error) {
    std::cerr << error.what() << '\n';
    return 1;
  }
}
