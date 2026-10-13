#pragma once

#include "legacy.hpp"

namespace sharded_g_test {
inline void collect(Observation &result, const GraSuUpdateCounters &c, MemoryBackend &backend) {
  const auto traffic = backend.traffic_stats();
  require(backend.outstanding() == 0 &&
              traffic.reads.bytes == c.update_read_bytes + c.row_read_bytes + c.binary_read_bytes + c.pma_read_bytes &&
              traffic.writes.bytes == c.pma_write_bytes, "candidate full byte ledger mismatch");
  result.cycles += c.end_cycle - c.start_cycle;
  result.reads += traffic.reads.bytes;
  result.writes += traffic.writes.bytes;
  result.cache += c.cache_updates;
  result.ddr += c.ddr_updates;
  result.rows += c.row_reads;
  result.probes += c.binary_probes;
  result.pma_reads += c.pma_read_bytes;
  result.pma_writes += c.pma_write_bytes;
}

inline Observation candidate_four_banks(const Fixture &f, unsigned latency) {
  Observation result;
  for (std::size_t shard = 0; shard < f.by_shard.size(); ++shard) {
    if (f.by_shard[shard].empty()) continue;
    Scheduler scheduler;
    const auto clock = scheduler.add_clock_mhz("G", 200);
    MockMemoryBackend backend("memory", clock, {4, latency, 1, 32, 64, true});
    scheduler.add_component(backend);
    auto config = candidate_config();
    // A prepared shard keeps its actual destination window, even in four banks.
    config.explicit_runtime_regions = true;
    config.pma_base = 0;
    config.pma_bases.fill(0);
    config.update_base = gt::kEdges;
    config.update_bases.fill(gt::kEdges);
    config.row_offset_base = gt::kRows;
    config.binary_base = gt::kBinary;
    initialize_legacy(backend, f.initial.partitions[shard]);
    GraSuPmaUpdateSystem system(scheduler, clock, backend, f.initial.partitions[shard], f.by_shard[shard], config);
    system.register_components();
    for (std::uint64_t cycle = 0; cycle < kLimit && !system.done() && !system.failed(); ++cycle) scheduler.step();
    require(system.done() && !system.failed(), "candidate four-bank cycle limit or failure");
    verify_legacy(backend, f.initial.partitions[shard], f.expected.partitions[shard]);
    require(system.materialized_partitioned_layout().partitions[0].segments == f.expected.partitions[shard].segments,
                "candidate four-bank materialized PMA differs");
    for (const auto &port : system.port_observations()) {
      const auto &s = port.stats;
      require(s.requests_accepted == s.requests_completed && s.beats_issued == s.beats_completed &&
                  s.zero_filled_write_bytes == 0, "candidate AXI requests not conserved");
    }
    collect(result, system.counters(), backend);
    system.unregister_components();
    scheduler.remove_component(backend);
    require(scheduler.component_count() == 0, "four-bank components leaked");
  }
  return result;
}

inline GraSuNativeConfig runtime_config(const GraSuReGraphRuntimePlan &plan, std::size_t shard) {
  auto config = candidate_config();
  config.explicit_runtime_regions = true;
  config.memory_channels = 32;
  const auto row = find_grasu_regraph_runtime_region(plan, shard, "row");
  const auto binary = find_grasu_regraph_runtime_region(plan, shard, "binary");
  config.row_channels.fill(row.channel);
  config.row_offset_base = row.channel_offset_bytes;
  config.binary_channels.fill(binary.channel);
  config.binary_base = binary.channel_offset_bytes;
  for (std::size_t bank = 0; bank < 4; ++bank) {
    const auto pma = find_grasu_regraph_runtime_region(plan, shard, "pma" + std::to_string(bank));
    config.pma_channels[bank] = pma.channel;
    config.pma_bases[bank] = pma.channel_offset_bytes;
  }
  return config;
}

struct Snapshot {
  GraSuReGraphBufferRegion region;
  std::vector<std::uint8_t> bytes;
};

inline Observation candidate_sharded(const Fixture &f, unsigned latency) {
  Scheduler scheduler;
  const auto clock = scheduler.add_clock_mhz("G", 200);
  MockMemoryBackend backend("memory", clock, {32, latency, 1, 32, 64, true});
  scheduler.add_component(backend);
  auto config = candidate_config();
  config.memory_channels = 32;
  GraSuShardedPmaUpdateSystem system(scheduler, clock, backend, f.initial, f.updates, config,
                                    kGraSuReGraphU55cChannelCapacityBytes);
  const auto &plan = system.runtime_plan();
  for (const auto &region : plan.regions) {
    if (region.name.starts_with("update")) continue;
    backend.initialize_payload(region.channel, region.channel_offset_bytes,
        region.name.starts_with("pma") ? blank(region.allocated_bytes)
                                       : std::vector<std::uint8_t>(region.allocated_bytes, 0xa5));
  }
  for (std::size_t shard = 0; shard < f.by_shard.size(); ++shard)
    initialize_grasu_pma_layout_payloads(backend, f.initial.partitions[shard], runtime_config(plan, shard));
  std::vector<Snapshot> snapshots;
  for (const auto &region : plan.regions) {
    if (region.name.starts_with("update")) continue;
    snapshots.push_back({region, backend.inspect_payload(region.channel, region.channel_offset_bytes,
                                                         region.allocated_bytes)});
  }
  system.register_components();
  for (std::uint64_t cycle = 0; cycle < kLimit && !system.done() && !system.failed(); ++cycle) {
    scheduler.step();
    system.advance_if_complete();
  }
  require(system.done() && !system.failed(), "actual sharded candidate cycle limit or failure");
  const auto materialized = system.materialized_partitioned_layout();
  for (std::size_t shard = 0; shard < f.by_shard.size(); ++shard)
    require(materialized.partitions[shard].segments == f.expected.partitions[shard].segments &&
                materialized.partitions[shard].row_slot_bounds == f.initial.partitions[shard].row_slot_bounds,
            "actual sharded materialized complete PMA or row geometry differs");
  for (auto &snapshot : snapshots) {
    const auto &region = snapshot.region;
    if (region.name.starts_with("pma")) {
      const auto bank = std::stoul(region.name.substr(3));
      const auto &part = f.expected.partitions[region.shard];
      for (std::size_t s = 0; s < part.segments.size(); ++s)
        if (s % 2 * 2 + (s / 2 >= kCache) == bank) segment_bytes(snapshot.bytes, s / 2, part.segments[s]);
    }
    require(backend.inspect_payload(region.channel, region.channel_offset_bytes, region.allocated_bytes) == snapshot.bytes,
            "actual sharded physical buffer, metadata, untouched shard or padding differs");
  }
  Observation result;
  collect(result, system.counters(), backend);
  system.unregister_components();
  scheduler.remove_component(backend);
  require(scheduler.component_count() == 0, "sharded components leaked");
  return result;
}
} // namespace sharded_g_test
