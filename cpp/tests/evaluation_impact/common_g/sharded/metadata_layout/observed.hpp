#pragma once

#include "../real_fixture.hpp"
#include "layout.hpp"
#include "../../diagnostics.hpp"

namespace sharded_g_test {
struct MetadataObservation {
  Observation work;
  common_g::Diagnostics diagnostics;
  GraSuNativeConfig config;
  std::size_t extra_metadata_bytes{}, allocated_bytes{}, channel_span_bytes{}, used_channels{};
  std::size_t row_bytes{}, binary_bytes{};
};

inline MetadataObservation observe_runtime(const RealFixture &f, unsigned latency, const std::string &arm) {
  Scheduler scheduler;
  const auto clock = scheduler.add_clock_mhz("G", 200);
  MockMemoryBackend backend("memory", clock, {32, latency, 1, 32, 64, true});
  scheduler.add_component(backend);
  MetadataLayout mapped(backend, f, arm);
  GraSuPmaUpdateSystem system(scheduler, clock, backend, f.initial.partitions[0], f.updates, mapped.config);
  MetadataObservation result;
  result.config = mapped.config;
  result.extra_metadata_bytes = mapped.extra_metadata_bytes;
  result.row_bytes = mapped.row_bytes;
  result.binary_bytes = mapped.binary_bytes;
  result.allocated_bytes = mapped.plan.total_allocated_bytes;
  for (const auto bytes : mapped.plan.channel_load_bytes) {
    result.channel_span_bytes += bytes;
    result.used_channels += bytes != 0;
  }
  system.register_components();
  for (std::uint64_t cycle = 1; cycle <= kLimit && !system.done() && !system.failed(); ++cycle) {
    scheduler.step();
    result.diagnostics.sample(system, cycle);
  }
  require(system.done() && !system.failed(), "observed runtime cycle limit or failure");
  const auto materialized = system.materialized_partitioned_layout().partitions[0];
  require(materialized.segments == f.expected.partitions[0].segments &&
              materialized.row_slot_bounds == f.initial.partitions[0].row_slot_bounds,
          "observed materialized PMA differs");
  mapped.verify(backend, f);
  result.diagnostics.finish(system);
  for (const auto &port : result.diagnostics.ports) {
    const auto &s = port.stats;
    require(s.requests_accepted == s.requests_completed && s.beats_issued == s.beats_completed &&
                s.zero_filled_write_bytes == 0, "observed AXI requests not conserved");
  }
  collect(result.work, system.counters(), backend);
  system.unregister_components();
  scheduler.remove_component(backend);
  require(scheduler.component_count() == 0, "observed components leaked");
  return result;
}
} // namespace sharded_g_test
