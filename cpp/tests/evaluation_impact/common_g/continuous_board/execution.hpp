#pragma once

#include "device.hpp"

namespace continuous_g {
template <typename State>
void run_batches(State& model, Device* device) {
  const bool board = device != nullptr;
  for (unsigned batch = 0; batch < 3; ++batch) {
    const auto begin = Clock::now();
    const auto updates = model.pack_batch(batch);
    const double preparation_ms = milliseconds(begin);
    auto phase = Clock::now();
    const auto transfers = board ? device->transfer(updates) : std::vector<Event>{};
    const double transfer_wall_ms = milliseconds(phase);
    phase = Clock::now();
    const auto kernels = board ? device->run(updates) : std::vector<Event>{};
    const double launch_wait_ms = milliseconds(phase);
    const double g_ready_wall_ms = milliseconds(begin);
    phase = Clock::now();
    model.advance(batch, updates);
    const double oracle_ms = milliseconds(phase);
    phase = Clock::now();
    const auto observed = board ? device->readback(model) : model.expected;
    const double verification_readback_ms = milliseconds(phase);
    const auto words = model.check(observed);
    if (!board && batch) {
      std::vector<Words> restored;
      for (const auto& shard : model.packed) restored.push_back(shard.pma_words);
      bool rejected = false;
      try { model.check(restored); } catch (const std::runtime_error&) { rejected = true; }
      check_input(rejected, "restore-between-batches fault escaped oracle");
    }
    const auto [busy_ms, span_ms] = event_window(kernels);
    for (const auto* events : {&transfers, &kernels}) for (const auto& event : *events) {
      const auto times = event.times();
      std::cout << "CONTINUOUS_G_EVENT {\"batch\":" << batch << ",\"shard\":" << event.shard
                << ",\"role\":\"" << event.role << "\",\"queued_ns\":" << times[0]
                << ",\"submit_ns\":" << times[1] << ",\"start_ns\":" << times[2]
                << ",\"end_ns\":" << times[3] << "}" << std::endl;
    }
    std::cout << "CONTINUOUS_G_ROW {\"batch\":" << batch << ",\"board\":" << (board ? "true" : "false")
              << ",\"updates\":" << model.ends[batch + 1] - model.ends[batch]
              << ",\"edges\":" << model.state.size() << ",\"checked_words\":" << words
              << ",\"host_preparation_ms\":" << preparation_ms << ",\"transfer_wall_ms\":" << transfer_wall_ms
              << ",\"launch_wait_ms\":" << launch_wait_ms << ",\"g_ready_wall_ms\":" << g_ready_wall_ms
              << ",\"kernel_busy_ms\":" << busy_ms << ",\"kernel_span_ms\":" << span_ms
              << ",\"oracle_ms\":" << oracle_ms << ",\"verification_readback_ms\":" << verification_readback_ms
              << ",\"complete_state_pass\":true,\"metadata_pass\":true,\"restored_pma\":false}" << std::endl;
  }
}
}  // namespace continuous_g
