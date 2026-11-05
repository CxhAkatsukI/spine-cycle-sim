#pragma once

#include "update_preparation.hpp"
#include "../handoff/memory.hpp"
#include "spine_sim/grasu_native.hpp"
#include <iostream>

namespace figure_refresh {
inline void validate_grasu_image(MemoryBackend& backend, const GraSuPartitionedPmaLayout& actual,
                                 const GraSuPartitionedPmaLayout& expected,
                                 const GraSuReGraphRuntimePlan& plan) {
  for (std::size_t p = 0; p < actual.partitions.size(); ++p) {
    const auto& a = actual.partitions[p];
    const auto& e = expected.partitions[p];
    require(a.row_slot_bounds == e.row_slot_bounds && a.binary_heads == e.binary_heads &&
        a.segments == e.segments, "resident G layout differs from the independent edit oracle");
    const auto config = handoff_test::shard_config(plan, p, plan.max_cache_segments);
    for (std::size_t s = 0; s < e.segments.size(); ++s) {
      const auto local = s / 2;
      const auto lane = (s % 2) * 2 + (local >= plan.max_cache_segments ? 1 : 0);
      const auto bytes = backend.inspect_payload(config.pma_channels[lane],
          config.pma_bases[lane] + local * 64, 64);
      for (std::size_t slot = 0; slot < e.segments[s].size(); ++slot) {
        const auto value = e.segments[s][slot];
        for (std::size_t byte = 0; byte < sizeof(value); ++byte)
          require(bytes.at(slot * sizeof(value) + byte) == static_cast<std::uint8_t>(value >> (byte * 8)),
                  "resident G backend PMA bytes differ from the independent edit oracle");
      }
    }
  }
}

inline void update_grasu(const wc::Input& input, Scheduler& scheduler, ClockId clock,
                         MemoryBackend& backend, std::uint64_t maximum,
                         std::size_t batches) {
  require(batches > 1 && batches <= input.updates.size(), "batch count would create empty G batches");
  handoff_test::Fixture fixture{};
  fixture.layout = reserved_grasu(input);
  fixture.updates = input.updates;
  const auto expected = handoff_test::edited_layout(fixture);
  auto config = GraSuNativeConfig{};
  config.pma_word_abi = GraSuPmaWordAbi::kWeightedFullWord;
  config.cache_segments_per_half = 131072;
  config.compact_parallel_search = config.compact_finite_search = true;
  config.compact_search_contexts = 64;
  config.compact_metadata_credits = 32;
  config.initialize_pma_payload = false;

  std::vector<std::size_t> capacity(fixture.layout.partitions.size());
  for (std::size_t index = 0; index < batches; ++index) {
    std::vector<std::size_t> counts(capacity.size());
    for (const auto& update : grasu_batch(input, index, batches))
      ++counts.at(fixture.layout.partition_for_destination(update.destination));
    for (std::size_t shard = 0; shard < capacity.size(); ++shard)
      capacity[shard] = std::max(capacity[shard], counts[shard]);
  }
  GraSuShardedPmaUpdateSystem g(scheduler, clock, backend, fixture.layout,
      grasu_batch(input, 0, batches), config, kGraSuReGraphU55cChannelCapacityBytes, capacity);
  const auto& plan = g.runtime_plan();
  for (std::size_t p = 0; p < fixture.layout.partitions.size(); ++p)
    initialize_grasu_pma_layout_payloads(backend, fixture.layout.partitions[p],
        handoff_test::shard_config(plan, p, config.cache_segments_per_half));
  fixture.layout = {};
  scheduler.add_component(backend);

  for (std::size_t index = 0; index < batches; ++index) {
    const auto batch = grasu_batch(input, index, batches);
    if (index) g.prepare_batch(batch);
    const auto before = backend.traffic_stats();
    g.register_components();
    while (!g.done() && !g.failed() && scheduler.clock(clock).completed_cycles < maximum) {
      scheduler.step();
      g.advance_if_complete();
    }
    require(g.done() && !g.failed() && backend.outstanding() == 0,
            "persistent G failed or exhausted its total cycle budget");
    const auto c = g.counters();
    const auto traffic = subtract_memory_traffic(backend.traffic_stats(), before);
    require(c.updates == batch.size() && c.update_read_bytes == batch.size() * 8 &&
        traffic.reads.bytes == c.update_read_bytes + c.row_read_bytes + c.binary_read_bytes + c.pma_read_bytes &&
        traffic.writes.bytes == c.pma_write_bytes, "persistent G byte ledger mismatch");
    std::cout << "WARM_BATCH {\"batch\":" << index << ",\"updates\":" << c.updates
        << ",\"cycles\":" << c.end_cycle - c.start_cycle << ",\"read_bytes\":" << traffic.reads.bytes
        << ",\"write_bytes\":" << traffic.writes.bytes << "}" << std::endl;
    g.unregister_components();
  }
  require(handoff_test::edge_set(g.live_edges()) == handoff_test::edge_set(input.after.edges),
          "resident G final graph differs from the insertion oracle");
  validate_grasu_image(backend, g.materialized_partitioned_layout(), expected, plan);
  const auto traffic = backend.traffic_stats();
  std::cout << "WARM_RESULT {\"arm\":\"gr\",\"cycles\":" << scheduler.clock(clock).completed_cycles
      << ",\"read_bytes\":" << traffic.reads.bytes << ",\"write_bytes\":" << traffic.writes.bytes
      << ",\"correctness\":true,\"physical_image_checked\":true,\"ledger_closed\":true}" << std::endl;
}
} // namespace figure_refresh
