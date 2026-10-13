#pragma once

#include "execution.hpp"

#include <iostream>
#include <memory>

namespace sharded_g_test::lifecycle {
inline void exact_wrapper_check(const Batch &input, unsigned latency, const Residency &,
                                const Observation &result, const std::vector<std::size_t> &, std::size_t) {
  const auto fresh = candidate_sharded(input, latency);
  require(fresh.cycles == result.cycles && fresh.reads == result.reads && fresh.writes == result.writes,
          "persistent manual sequencing differs from production sharded wrapper");
}

template <class Input, class WrapperCheck = decltype(&exact_wrapper_check)>
inline void run(const Input &fixture, const std::string &name, unsigned latency,
                const std::string &arm, const std::string &state, std::size_t vertices,
                WrapperCheck check_wrapper = exact_wrapper_check) {
  require(latency == 64 || latency == 128, "undeclared resident memory latency");
  require(arm == "original-prepared-shards" || arm == "candidate-runtime-23" ||
              arm == "runtime-both-copies", "undeclared resident arm");
  Scheduler scheduler;
  const auto clock = scheduler.add_clock_mhz("G", 200);
  MockMemoryBackend backend("memory", clock, {32, latency, 1, 32, 64, true});
  std::unique_ptr<Residency> resident;
  if (arm != "original-prepared-shards") {
    scheduler.add_component(backend);
    resident = std::make_unique<Residency>(backend, fixture, arm == "runtime-both-copies");
  }
  std::cout << "RESIDENT_G_RESULT {\"case\":\"" << name << "\",\"arm\":\"" << arm
      << "\",\"latency\":" << latency << ",\"vertices\":" << vertices
      << ",\"total_shards\":" << fixture.maximum_updates.size()
      << ",\"timing_kind\":\"declared_prediction\",\"batches\":[";
  for (std::size_t batch = 0; batch < fixture.batches.size(); ++batch) {
    const auto &input = fixture.batches[batch];
    const auto result = resident ? execute_batch(scheduler, clock, backend, *resident, input, batch)
                                 : original(input, latency);
    if (arm == "candidate-runtime-23") {
      check_wrapper(input, latency, *resident, result, fixture.maximum_updates, batch);
    }
    save_state(state + ".batch" + std::to_string(batch), input.expected);
    std::cout << (batch ? "," : "");
    write_work(std::cout, input, result);
  }
  save_state(state, fixture.batches.back().expected);
  std::cout << "],\"resources\":";
  if (resident) {
    const auto &plan = resident->plan;
    std::size_t spans = 0, used = 0;
    for (const auto bytes : plan.channel_load_bytes) { spans += bytes; used += bytes != 0; }
    std::cout << "{\"allocated_bytes\":" << plan.total_allocated_bytes
        << ",\"channel_span_bytes\":" << spans << ",\"used_channels\":" << used
        << ",\"extra_metadata_bytes\":" << resident->extra_bytes
        << ",\"initial_metadata_upload_bytes\":" << resident->metadata_upload_bytes
        << ",\"interbatch_metadata_upload_bytes\":0,\"metadata_reservations_fixed\":true,\"regions\":[";
    for (std::size_t i = 0; i < plan.regions.size(); ++i) {
      const auto &r = plan.regions[i];
      std::cout << (i ? "," : "") << "{\"shard\":" << r.shard << ",\"name\":\"" << r.name
          << "\",\"channel\":" << r.channel << ",\"base\":" << r.channel_offset_bytes
          << ",\"logical_bytes\":" << r.logical_bytes << ",\"allocated_bytes\":" << r.allocated_bytes << "}";
    }
    std::cout << "]}";
    scheduler.remove_component(backend);
  } else std::cout << "null";
  std::cout << "}\n";
}
} // namespace sharded_g_test::lifecycle
