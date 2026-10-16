#pragma once

#include "device.hpp"

namespace metadata_g {
inline void emit_events(unsigned generation, int batch, const std::vector<continuous_g::Event>& events) {
  for (const auto& event : events) {
    const auto times = event.times();
    std::cout << "METADATA_G_EVENT {\"generation\":" << generation << ",\"batch\":" << batch
              << ",\"shard\":" << event.shard << ",\"role\":\"" << event.role
              << "\",\"queued_ns\":" << times[0] << ",\"submit_ns\":" << times[1]
              << ",\"start_ns\":" << times[2] << ",\"end_ns\":" << times[3] << "}" << std::endl;
  }
}

inline void execute(Model& model, continuous_g::Device* device, bool stale) {
  using namespace continuous_g;
  const bool board = device != nullptr;
  check_input(!board || !stale, "stale negative control is CPU-model-only");
  const auto original = board ? handles(*device) : Handles{};
  const auto old_graph = model.graph;
  auto simulated = model.expected;
  for (unsigned generation = 0; generation < 2; ++generation) {
    const auto start = Clock::now();
    if (generation) model.remap();
    const double prepare_ms = milliseconds(start);
    const auto begin_dma = Clock::now();
    const auto dma = board && generation ? refresh(*device, model, original) : std::vector<Event>{};
    const double dma_ms = milliseconds(begin_dma);
    emit_events(generation, -1, dma);
    std::cout << "METADATA_G_GENERATION {\"generation\":" << generation
              << ",\"metadata_preparation_ms\":" << prepare_ms << ",\"metadata_dma_ms\":" << dma_ms
              << ",\"same_bos\":true,\"restored_pma\":false}" << std::endl;
    for (unsigned batch = 0; batch < 3; ++batch) {
      const auto begin = Clock::now();
      const auto updates = model.pack_batch(batch);
      const double host_ms = milliseconds(begin);
      auto phase = Clock::now();
      const auto transfers = board ? device->transfer(updates) : std::vector<Event>{};
      const double transfer_ms = milliseconds(phase);
      phase = Clock::now();
      const auto kernels = board ? device->run(updates) : std::vector<Event>{};
      const double launch_ms = milliseconds(phase), ready_ms = milliseconds(begin);
      phase = Clock::now();
      model.advance(batch, updates);
      if (!board)
        apply_physical(stale && generation ? old_graph : model.graph, simulated, updates, updates);
      const double oracle_ms = milliseconds(phase);
      phase = Clock::now();
      const auto observed = board ? device->readback(model) : simulated;
      const double readback_ms = milliseconds(phase);
      const auto words = check_words(observed, model.expected);
      if (board) check_input(handles(*device) == original, "batch reallocated resident BOs");
      const auto [busy, span] = event_window(kernels);
      emit_events(generation, batch, transfers);
      emit_events(generation, batch, kernels);
      std::cout << "METADATA_G_ROW {\"generation\":" << generation << ",\"batch\":" << batch
                << ",\"board\":" << (board ? "true" : "false") << ",\"updates\":" << model.batches[batch].size()
                << ",\"edges\":" << model.state.size() << ",\"checked_words\":" << words
                << ",\"host_preparation_ms\":" << host_ms << ",\"transfer_wall_ms\":" << transfer_ms
                << ",\"launch_wait_ms\":" << launch_ms << ",\"g_ready_wall_ms\":" << ready_ms
                << ",\"kernel_busy_ms\":" << busy << ",\"kernel_span_ms\":" << span
                << ",\"oracle_ms\":" << oracle_ms << ",\"verification_readback_ms\":" << readback_ms
                << ",\"complete_state_pass\":true,\"metadata_pass\":true,\"restored_pma\":false}" << std::endl;
    }
  }
}
}  // namespace metadata_g
