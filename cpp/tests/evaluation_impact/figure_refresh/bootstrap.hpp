#pragma once

#include "input.hpp"
#include <iostream>

// Link wrapping observes the unchanged core constructor's actual payloads.
// Suppressing only simulator storage keeps its page-map bookkeeping out of
// host preparation; normal timed runs always forward to the real backend.
extern "C" void refresh_real_initialize(spine::sim::MemoryBackend*, std::size_t,
    std::uint64_t, const std::vector<std::uint8_t>&)
    asm("__real__ZN5spine3sim13MemoryBackend18initialize_payloadEmmRKSt6vectorIhSaIhEE");
extern "C" void refresh_wrap_initialize(spine::sim::MemoryBackend*, std::size_t,
    std::uint64_t, const std::vector<std::uint8_t>&)
    asm("__wrap__ZN5spine3sim13MemoryBackend18initialize_payloadEmmRKSt6vectorIhSaIhEE");

namespace figure_refresh {
struct BootstrapCapture {
  inline static thread_local BootstrapCapture* active = nullptr;
  std::uint64_t graph_bytes{}, directory_bytes{}, metadata_bytes{}, batch_bytes{}, calls{};
  const MemoryBackend* physical{};
  SpineL0Config config;
  explicit BootstrapCapture(const SpineL0Config& c, const MemoryBackend* p = nullptr) : physical(p), config(c) {
    require(active == nullptr, "nested bootstrap capture");
    active = this;
  }
  ~BootstrapCapture() { active = nullptr; }
  void observe(std::size_t channel, std::uint64_t address, const std::vector<std::uint8_t>& data) {
    ++calls;
    if (channel < 16) graph_bytes += data.size();
    else if (channel == 16 && address == config.sorted_edges_base) batch_bytes += data.size();
    else if (channel == 16) directory_bytes += data.size();
    else if (channel == 20) metadata_bytes += data.size();
    else throw std::logic_error("unexpected Spine bootstrap channel");
    if (physical && channel < 16)
      require(physical->inspect_payload(channel, address, data.size()) == data,
              "physical graph/index payload differs from final resident image");
    // Slice lengths and addresses are published in the first seven words;
    // epochs are runtime-owned and intentionally not reset to bootstrap 1.
    if (physical && channel == 20 && data.size() == 64)
      require(physical->inspect_payload(channel, address, 56) ==
          std::vector<std::uint8_t>(data.begin(), data.begin() + 56),
          "physical slice publication differs from final resident image");
  }
  std::uint64_t initial_bytes() const { return graph_bytes + directory_bytes + metadata_bytes; }
};

inline void constructor_image(SpineL0State& state, const SpineEdgeSlice& batch, const SpineL0Config& config) {
  MockMemoryBackend scratch("bootstrap", 0, {32, 1, 1, 32, 32, true});
  std::vector<std::unique_ptr<FixedAxiPort>> graph;
  SpineL0Ports ports;
  for (std::size_t i = 0; i < ports.graph.size(); ++i) {
    graph.push_back(std::make_unique<FixedAxiPort>("bootstrap-graph", 0,
        FixedAxiPortConfig{.memory_channels = 32, .channel = i,
                          .initiator_id = static_cast<std::uint32_t>(800 + i)}, scratch));
    ports.graph[i] = graph.back().get();
  }
  FixedAxiPort sorted("bootstrap-sorted", 0, {.memory_channels = 32, .channel = 16, .initiator_id = 816}, scratch);
  FixedAxiPort metadata("bootstrap-meta", 0, {.memory_channels = 32, .channel = 20, .initiator_id = 820}, scratch);
  FixedAxiPort result("bootstrap-result", 0, {.memory_channels = 32, .channel = 21, .initiator_id = 821}, scratch);
  ports.sorted_edges = &sorted; ports.metadata = &metadata; ports.result = &result;
  SpineL0Maintenance image("bootstrap-image", 0, config, batch, ports, state);
}

inline void validate_physical_image(SpineL0State state, std::uint32_t vertices,
                                    const SpineL0Config& config, const MemoryBackend& backend) {
  BootstrapCapture capture(config, &backend);
  constructor_image(state, SpineEdgeSlice{.vertices = vertices, .edges = {}, .case_name = "physical-oracle"}, config);
  require(capture.graph_bytes > 0 && capture.calls > 0, "physical image validation did not observe constructor");
}
} // namespace figure_refresh

extern "C" void refresh_wrap_initialize(spine::sim::MemoryBackend* backend, std::size_t channel,
    std::uint64_t address, const std::vector<std::uint8_t>& data) {
  if (auto* capture = figure_refresh::BootstrapCapture::active) capture->observe(channel, address, data);
  else refresh_real_initialize(backend, channel, address, data);
}
