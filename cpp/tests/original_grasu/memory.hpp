#pragma once

#include <algorithm>
#include <functional>
#include <memory>
#include <vector>

#include "spine_sim/original_grasu/types.hpp"
#include "spine_sim/scheduler.hpp"

namespace grasu_test {
namespace g = spine::sim::original_grasu;
using namespace spine::sim;

struct Link {
  unsigned bank{}, width{};
  Fifo<AxiRequest>* requests;
  Fifo<AxiResponse>* responses;
  Fifo<AxiReadBeatResponse>* beats;
  AxiMaster* master;
  g::Port port() const { return {*requests, *responses}; }
  g::StreamPort stream() const { return {port(), *beats}; }
};

// A separate U250-like four-bank study fixture, not the production HBM model.
class Memory {
 public:
  Memory(unsigned depth, unsigned latency, unsigned credits)
      : clock(scheduler.add_clock_mhz("G", 200)), depth_(depth) {
    if (!depth || !latency || !credits) throw std::invalid_argument("G memory limits must be positive");
    backend = make<MockMemoryBackend>("memory", clock, MockMemoryConfig{
        .channels = 4, .latency_cycles = latency, .accepts_per_channel_per_cycle = 1,
        .max_outstanding_per_channel = credits, .response_queue_depth = 64,
        .registered_round_robin_arbitration = true});
  }
  ~Memory() {
    for (auto* component : registered_) scheduler.remove_component(*component);
    while (!owned_.empty()) owned_.pop_back();
  }
  template <typename T, typename... Args> T* make(Args&&... args) {
    auto item = std::make_unique<T>(std::forward<Args>(args)...);
    auto* pointer = item.get(); owned_.push_back(std::move(item)); return pointer;
  }
  template <typename T> Fifo<T>* queue(const std::string& name) {
    auto* result = make<Fifo<T>>(name, clock, depth_);
    checks_.push_back([result] {
      return result->empty() && result->stats().pushes == result->stats().pops &&
          result->stats().max_occupancy <= result->depth();
    });
    return result;
  }
  Link link(const std::string& name, unsigned bank, unsigned width, bool streaming = false) {
    auto* requests = queue<AxiRequest>(name + ".requests");
    auto* responses = queue<AxiResponse>(name + ".responses");
    auto* beats = streaming ? queue<AxiReadBeatResponse>(name + ".beats") : nullptr;
    auto* master = make<AxiMaster>(name, clock, AxiConfig{
        .initiator_id = static_cast<unsigned>(links.size() + 1), .data_width_bytes = width,
        .max_burst_beats = 16, .channels = 4, .channel_interleave_bytes = 64,
        .max_pending_requests = 16, .max_outstanding_bursts = 16,
        .address_accepts_per_cycle = 1, .beat_issues_per_cycle = 1,
        .response_beats_per_cycle = 1, .read_reorder_capacity = 32, .fixed_channel = bank},
        *requests, *responses, *backend, beats);
    Link result{bank, width, requests, responses, beats, master}; links.push_back(result); return result;
  }
  void register_components(bool reverse) {
    for (const auto& item : owned_) registered_.push_back(item.get());
    if (reverse) std::reverse(registered_.begin(), registered_.end());
    for (auto* item : registered_) scheduler.add_component(*item);
  }
  bool drained() const {
    return backend->outstanding() == 0 &&
        std::all_of(links.begin(), links.end(), [](const auto& link) { return link.master->idle(); }) &&
        std::all_of(checks_.begin(), checks_.end(), [](const auto& check) { return check(); });
  }
  Scheduler scheduler;
  ClockId clock;
  MockMemoryBackend* backend;
  std::vector<Link> links;
 private:
  unsigned depth_;
  std::vector<std::unique_ptr<Component>> owned_;
  std::vector<Component*> registered_;
  std::vector<std::function<bool()>> checks_;
};
}  // namespace grasu_test
