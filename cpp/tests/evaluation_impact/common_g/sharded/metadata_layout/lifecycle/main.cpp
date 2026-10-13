#include "execution.hpp"

#include <iostream>
#include <memory>

int main(int argc, char **argv) {
  namespace sg = sharded_g_test;
  namespace lc = sg::lifecycle;
  try {
    if (argc != 5) throw std::invalid_argument("usage: resident G CASE LATENCY ARM STATE");
    const std::string name(argv[1]), arm(argv[3]), state(argv[4]);
    const auto latency = std::stoul(argv[2]);
    sg::require(latency == 64 || latency == 128, "undeclared resident memory latency");
    sg::require(arm == "original-prepared-shards" || arm == "candidate-runtime-23" ||
                    arm == "runtime-both-copies", "undeclared resident arm");
    const lc::Fixture fixture(name);
    sg::Scheduler scheduler;
    const auto clock = scheduler.add_clock_mhz("G", 200);
    sg::MockMemoryBackend backend("memory", clock, {32, latency, 1, 32, 64, true});
    std::unique_ptr<lc::Residency> resident;
    if (arm != "original-prepared-shards") {
      scheduler.add_component(backend);
      resident = std::make_unique<lc::Residency>(backend, fixture, arm == "runtime-both-copies");
    }
    std::cout << "RESIDENT_G_RESULT {\"case\":\"" << name << "\",\"arm\":\"" << arm
        << "\",\"latency\":" << latency << ",\"vertices\":" << lc::Fixture::kVertices
        << ",\"total_shards\":3,\"timing_kind\":\"declared_prediction\",\"batches\":[";
    for (std::size_t batch = 0; batch < fixture.batches.size(); ++batch) {
      const auto &input = fixture.batches[batch];
      const auto result = resident ? lc::execute_batch(scheduler, clock, backend, *resident, input, batch)
                                   : sg::original(input, latency);
      if (arm == "candidate-runtime-23") {
        const auto fresh = sg::candidate_sharded(input, latency);
        sg::require(fresh.cycles == result.cycles && fresh.reads == result.reads && fresh.writes == result.writes,
                    "persistent manual sequencing differs from production sharded wrapper");
      }
      sg::save_state(state + ".batch" + std::to_string(batch), input.expected);
      std::cout << (batch ? "," : "");
      lc::write_work(std::cout, input, result);
    }
    sg::save_state(state, fixture.batches.back().expected);
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
  } catch (const std::exception &error) {
    std::cerr << error.what() << '\n';
    return 1;
  }
}
