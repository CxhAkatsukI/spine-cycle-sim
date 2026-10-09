#pragma once

#include <algorithm>
#include <functional>
#include <memory>
#include <string>
#include <vector>

#include "spine_sim/original_regraph/frontend_types.hpp"
#include "spine_sim/scheduler.hpp"

namespace original_regraph_memory_test {
using spine::sim::Fifo;

inline spine::sim::AxiConfig axi_config(unsigned initiator, std::size_t channel,
                                       std::size_t outstanding = 16) {
  return {.initiator_id = initiator, .data_width_bytes = 64, .max_burst_beats = 16,
          .channels = 32, .channel_interleave_bytes = 64, .max_pending_requests = 2,
          .max_outstanding_bursts = outstanding, .address_accepts_per_cycle = 1,
          .beat_issues_per_cycle = 1, .response_beats_per_cycle = 1,
          .read_reorder_capacity = 32, .fixed_channel = channel};
}

struct MemoryLink {
  Fifo<spine::sim::AxiRequest>* requests{};
  Fifo<spine::sim::AxiResponse>* responses{};
  Fifo<spine::sim::AxiReadBeatResponse>* beats{};
  spine::sim::AxiMaster* master{};
  spine::sim::original_regraph::ReadPort ports() const { return {*requests, *responses, *beats}; }
};

class MemoryFixture {
 public:
  MemoryFixture(std::size_t fifo_depth = 8, std::uint64_t memory_latency = 64)
      : clock(scheduler.add_clock_mhz("core", 210)), depth_(fifo_depth) {
    backend = make<spine::sim::MockMemoryBackend>("memory", clock, spine::sim::MockMemoryConfig{
        .channels = 32, .latency_cycles = memory_latency,
        .accepts_per_channel_per_cycle = 1, .max_outstanding_per_channel = 512,
        .response_queue_depth = 64, .registered_round_robin_arbitration = true});
  }

  ~MemoryFixture() {
    for (auto* component : registered_) scheduler.remove_component(*component);
    // AXI masters unbind callbacks into their FIFOs/backend during destruction.
    while (!owned_.empty()) owned_.pop_back();
  }

  template <typename T, typename... Args>
  T* make(Args&&... args) {
    auto value = std::make_unique<T>(std::forward<Args>(args)...);
    auto* pointer = value.get();
    owned_.push_back(std::move(value));
    return pointer;
  }

  template <typename T>
  Fifo<T>* queue(const std::string& name) {
    auto* pointer = make<Fifo<T>>(name, clock, depth_);
    queue_checks_.push_back([pointer] {
      return pointer->empty() && pointer->stats().pushes == pointer->stats().pops &&
             pointer->stats().max_occupancy <= pointer->depth();
    });
    return pointer;
  }

  MemoryLink port(const std::string& name, unsigned initiator, std::size_t channel,
                  std::size_t outstanding = 16) {
    MemoryLink link;
    link.requests = queue<spine::sim::AxiRequest>(name + ".requests");
    link.responses = queue<spine::sim::AxiResponse>(name + ".responses");
    link.beats = queue<spine::sim::AxiReadBeatResponse>(name + ".beats");
    link.master = make<spine::sim::AxiMaster>(name, clock, axi_config(initiator, channel, outstanding),
        *link.requests, *link.responses, *backend, link.beats);
    masters_.push_back(link.master);
    return link;
  }

  void register_components(bool reverse = false) {
    for (auto* component : registered_) scheduler.remove_component(*component);
    registered_.clear();
    for (const auto& component : owned_) registered_.push_back(component.get());
    if (reverse) std::reverse(registered_.begin(), registered_.end());
    for (auto* component : registered_) scheduler.add_component(*component);
  }

  bool drained() const {
    return backend->outstanding() == 0 &&
        std::all_of(masters_.begin(), masters_.end(), [](const auto* master) { return master->idle(); }) &&
        std::all_of(queue_checks_.begin(), queue_checks_.end(), [](const auto& check) { return check(); });
  }

  spine::sim::Scheduler scheduler;
  spine::sim::ClockId clock;
  spine::sim::MockMemoryBackend* backend{};

 private:
  std::size_t depth_{};
  std::vector<std::unique_ptr<spine::sim::Component>> owned_;
  std::vector<spine::sim::Component*> registered_;
  std::vector<spine::sim::AxiMaster*> masters_;
  std::vector<std::function<bool()>> queue_checks_;
};

}  // namespace original_regraph_memory_test
