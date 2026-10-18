#pragma once

#include "continuous_board/device.hpp"
#include "lease.hpp"

namespace matched_g {
inline void run(Model& model, const char* xclbin, unsigned index) {
  using namespace continuous_g;
  require_lease(index);
  auto phase = Clock::now();
  Device device(xclbin, index, model);
  const double setup_ms = milliseconds(phase);
  const auto begin = Clock::now();
  const auto batch = model.pack_batch();
  const double pack_ms = milliseconds(begin);
  phase = Clock::now();
  const auto transfers = device.transfer(batch);
  const double dma_ms = milliseconds(phase);
  phase = Clock::now();
  const auto kernels = device.run(batch);
  const double launch_wait_ms = milliseconds(phase), ready_ms = milliseconds(begin);
  phase = Clock::now();
  model.advance(batch);
  const double oracle_ms = milliseconds(phase);
  phase = Clock::now();
  const auto observed = device.readback(model);
  const auto checked_words = model.check(observed);
  const double readback_ms = milliseconds(phase);
  for (const auto* events : {&transfers, &kernels}) for (const auto& event : *events) {
    const auto times = event.times();
    std::cout << "MATCHED_G_EVENT {\"role\":\"" << event.role << "\",\"shard\":" << event.shard
              << ",\"queued_ns\":" << times[0] << ",\"submit_ns\":" << times[1]
              << ",\"start_ns\":" << times[2] << ",\"end_ns\":" << times[3] << "}\n";
  }
  const auto [busy_ms, span_ms] = event_window(kernels);
  std::cout << "MATCHED_G_BOARD {\"status\":\"PASS\",\"updates\":" << model.input.updates.size()
            << ",\"checked_words\":" << checked_words << ",\"one_time_setup_ms\":" << setup_ms
            << ",\"pack_ms\":" << pack_ms << ",\"dma_wall_ms\":" << dma_ms
            << ",\"launch_wait_ms\":" << launch_wait_ms << ",\"g_ready_wall_ms\":" << ready_ms
            << ",\"kernel_busy_ms\":" << busy_ms << ",\"kernel_span_ms\":" << span_ms
            << ",\"oracle_ms\":" << oracle_ms << ",\"verification_readback_ms\":" << readback_ms
            << ",\"complete_state_pass\":true,\"metadata_pass\":true}\n";
}
}  // namespace matched_g
