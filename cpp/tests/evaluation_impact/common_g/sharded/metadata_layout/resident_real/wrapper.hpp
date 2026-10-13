#pragma once

#include "../lifecycle/execution.hpp"

#include <iostream>

namespace sharded_g_test::resident_real {
inline bool equal(const Observation &a, const Observation &b) {
  return a.cycles == b.cycles && a.reads == b.reads && a.writes == b.writes &&
      a.cache == b.cache && a.ddr == b.ddr && a.rows == b.rows && a.probes == b.probes &&
      a.pma_reads == b.pma_reads && a.pma_writes == b.pma_writes;
}

inline Observation fresh_manual(const lifecycle::Batch &batch, unsigned latency,
                                const std::vector<std::size_t> &capacity) {
  struct View { const GraSuPartitionedPmaLayout &initial; };
  struct Input { std::array<View, 1> batches; const std::vector<std::size_t> &maximum_updates; };
  const Input input{{View{batch.initial}}, capacity};
  Scheduler scheduler;
  const auto clock = scheduler.add_clock_mhz("G", 200);
  MockMemoryBackend backend("memory", clock, {32, latency, 1, 32, 64, true});
  scheduler.add_component(backend);
  lifecycle::Residency resident(backend, input, false);
  const auto result = lifecycle::execute_batch(scheduler, clock, backend, resident, batch, 0);
  scheduler.remove_component(backend);
  require(scheduler.component_count() == 0, "fresh resident check leaked components");
  return result;
}

inline void check_wrapper(const lifecycle::Batch &batch, unsigned latency, const lifecycle::Residency &resident,
                          const Observation &result, const std::vector<std::size_t> &capacity, std::size_t index) {
  std::vector<std::size_t> counts;
  for (const auto &updates : batch.by_shard) counts.push_back(updates.size());
  const auto plan = build_grasu_regraph_runtime_plan(batch.initial, counts, kCache);
  const auto wrapper = candidate_sharded(batch, latency);
  const auto manual = fresh_manual(batch, latency, counts);
  require(equal(wrapper, manual), "manual sequence differs from production wrapper under identical batch layout");
  const auto fixed = fresh_manual(batch, latency, capacity);
  require(equal(result, fixed), "resident sequence differs from fresh replay under identical fixed layout");
  bool same = true;
  std::cerr << "RESIDENT_WRAPPER_CHECK {\"batch\":" << index << ",\"changed_regions\":[";
  for (const auto &region : plan.regions) {
    const auto &other = find_grasu_regraph_runtime_region(resident.plan, region.shard, region.name);
    if (region.channel == other.channel && region.channel_offset_bytes == other.channel_offset_bytes &&
        region.allocated_bytes == other.allocated_bytes) continue;
    std::cerr << (same ? "" : ",") << "{\"shard\":" << region.shard << ",\"name\":\"" << region.name
        << "\",\"wrapper_channel\":" << region.channel << ",\"resident_channel\":" << other.channel
        << ",\"wrapper_base\":" << region.channel_offset_bytes << ",\"resident_base\":" << other.channel_offset_bytes
        << ",\"wrapper_allocated\":" << region.allocated_bytes << ",\"resident_allocated\":" << other.allocated_bytes << "}";
    same = false;
  }
  require(!same || equal(wrapper, result), "identical wrapper/resident layout has different timing");
  std::cerr << "],\"resident_matches_wrapper_layout\":" << (same ? "true" : "false")
      << ",\"wrapper_cycles\":" << wrapper.cycles << ",\"manual_wrapper_cycles\":" << manual.cycles
      << ",\"resident_cycles\":" << result.cycles << ",\"fresh_resident_cycles\":" << fixed.cycles
      << ",\"full_counters_equal_in_each_layout\":true}\n";
}
} // namespace sharded_g_test::resident_real
