#pragma once

#include <cstddef>
#include <cstdint>
#include <string>
#include <utility>
#include <vector>

#include "spine_sim/axi.hpp"
#include "spine_sim/fifo.hpp"
#include "spine_sim/memory_backend.hpp"
#include "spine_sim/scheduler.hpp"

namespace spine::sim {

struct FixedAxiPortConfig {
  std::size_t memory_channels{};
  std::size_t channel{};
  std::uint32_t initiator_id{};
  std::size_t request_fifo_depth{32};
  std::size_t response_fifo_depth{32};
  std::size_t max_pending_requests{32};
  std::size_t max_outstanding_bursts{32};
};

class FixedAxiPort {
 public:
  FixedAxiPort(std::string name, ClockId clock_id,
               const FixedAxiPortConfig& config, MemoryBackend& backend)
      : requests_(name + "-requests", clock_id, config.request_fifo_depth),
        responses_(name + "-responses", clock_id, config.response_fifo_depth),
        master_(
            std::move(name), clock_id,
            AxiConfig{
                .initiator_id = config.initiator_id,
                .data_width_bytes = 64,
                .max_burst_beats = 16,
                .channels = config.memory_channels,
                .channel_interleave_bytes = 64,
                .max_pending_requests = config.max_pending_requests,
                .max_outstanding_bursts = config.max_outstanding_bursts,
                .address_accepts_per_cycle = 1,
                .beat_issues_per_cycle = 1,
                .response_beats_per_cycle = 4,
                .fixed_channel = config.channel,
            },
            requests_, responses_, backend),
        backend_(backend),
        channel_(config.channel) {}

  void register_components(Scheduler& scheduler) {
    scheduler.add_component(requests_);
    scheduler.add_component(master_);
    scheduler.add_component(responses_);
  }

  [[nodiscard]] Fifo<AxiRequest>& requests() noexcept { return requests_; }
  [[nodiscard]] Fifo<AxiResponse>& responses() noexcept { return responses_; }
  [[nodiscard]] AxiMaster& master() noexcept { return master_; }
  [[nodiscard]] const AxiMaster& master() const noexcept { return master_; }
  [[nodiscard]] std::size_t channel() const noexcept { return channel_; }
  void initialize_payload(std::uint64_t address,
                          const std::vector<std::uint8_t>& data) {
    backend_.initialize_payload(channel_, address, data);
  }
  void fill_payload(std::uint64_t address, std::uint64_t bytes,
                    std::uint8_t value) {
    backend_.fill_payload(channel_, address, bytes, value);
  }
  [[nodiscard]] bool idle() const noexcept {
    return requests_.empty() && responses_.empty() && master_.idle();
  }

 private:
  Fifo<AxiRequest> requests_;
  Fifo<AxiResponse> responses_;
  AxiMaster master_;
  MemoryBackend& backend_;
  std::size_t channel_{};
};

}  // namespace spine::sim
