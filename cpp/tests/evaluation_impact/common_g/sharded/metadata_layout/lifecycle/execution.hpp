#pragma once

#include "residency.hpp"

namespace sharded_g_test::lifecycle {
inline Observation execute_batch(Scheduler &scheduler, ClockId clock, MemoryBackend &backend,
                                 Residency &resident, const Batch &batch, std::size_t batch_index) {
  Observation result;
  const auto before = backend.traffic_stats();
  const auto start = scheduler.clock(clock).completed_cycles;
  for (std::size_t shard = 0; shard < batch.by_shard.size(); ++shard) {
    if (batch.by_shard[shard].empty()) continue;
    auto config = resident.config(shard);
    // Backend traffic identities are permanent; old masters are destroyed
    // between batches, so this namespace does not add concurrent ports.
    config.initiator_base += static_cast<std::uint32_t>(batch_index * 128);
    GraSuPmaUpdateSystem system(scheduler, clock, backend, batch.initial.partitions[shard],
                               batch.by_shard[shard], config);
    system.register_components();
    for (std::uint64_t cycle = 0; cycle < kLimit && !system.done() && !system.failed(); ++cycle) scheduler.step();
    require(system.done() && !system.failed(), "resident batch cycle limit or failure");
    const auto observed = system.materialized_partitioned_layout().partitions[0];
    require(observed.segments == batch.expected.partitions[shard].segments &&
                observed.row_slot_bounds == batch.initial.partitions[shard].row_slot_bounds &&
                observed.binary_heads == batch.initial.partitions[shard].binary_heads,
            "resident materialized state or fixed metadata differs");
    for (const auto &port : system.port_observations()) {
      const auto &stats = port.stats;
      require(stats.requests_accepted == stats.requests_completed && stats.beats_issued == stats.beats_completed &&
                  stats.zero_filled_write_bytes == 0, "resident AXI requests not conserved");
    }
    const auto c = system.counters();
    result.cache += c.cache_updates;
    result.ddr += c.ddr_updates;
    result.rows += c.row_reads;
    result.probes += c.binary_probes;
    result.pma_reads += c.pma_read_bytes;
    result.pma_writes += c.pma_write_bytes;
    system.unregister_components();
  }
  const auto after = backend.traffic_stats();
  result.cycles = scheduler.clock(clock).completed_cycles - start;
  result.reads = after.reads.bytes - before.reads.bytes;
  result.writes = after.writes.bytes - before.writes.bytes;
  require(backend.outstanding() == 0 && scheduler.component_count() == 1 &&
              result.reads == batch.updates.size() * 8 + result.rows * 8 + result.probes * 8 + result.pma_reads &&
              result.writes == result.pma_writes, "resident complete byte ledger or component drain differs");
  resident.verify(backend, batch.expected);
  return result;
}

inline void write_work(std::ostream &out, const Batch &batch, const Observation &work) {
  const auto pma = batch.touched() * 2 * kCache * 64;
  require(work.rows == batch.updates.size() && work.probes == batch.probes &&
              work.cache == batch.updates.size() && work.ddr == 0 && work.pma_reads == pma && work.pma_writes == pma,
          "resident complete cache or operation/search ledger differs");
  out << "{\"cycles\":" << work.cycles << ",\"physical_updates\":" << batch.updates.size()
      << ",\"updated_shards\":" << batch.touched() << ",\"read_bytes\":" << work.reads
      << ",\"write_bytes\":" << work.writes << ",\"pma_read_bytes\":" << work.pma_reads
      << ",\"pma_write_bytes\":" << work.pma_writes << ",\"cache_updates\":" << work.cache
      << ",\"ddr_updates\":" << work.ddr << ",\"row_reads\":" << work.rows
      << ",\"binary_probes\":" << work.probes << ",\"multi_segment_updates\":" << batch.multi_segment_updates
      << ",\"full_payload_pass\":true}";
}
} // namespace sharded_g_test::lifecycle
