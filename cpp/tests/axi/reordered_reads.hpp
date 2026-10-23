#pragma once

#include "../../src/detail/backend_response_selection.hpp"
#include "spine_sim/fixed_axi_port.hpp"

#include <deque>
#include <numeric>

namespace axi_test {
using namespace spine::sim;

// A finite test backend delays the first beat in each group, while later
// reads complete early. This reproduces DRAM row-hit/miss response reordering.
class ReorderedReads final : public MemoryBackend {
 public:
  explicit ReorderedReads(ClockId clock) : MemoryBackend("reordered", clock) {}

  bool try_reserve(const BackendRequestHeader &header) override {
    if (header.initiator_id != 1 || header.channel != 0 ||
        header.operation != MemoryOperation::kRead)
      throw std::logic_error("unexpected test backend request");
    return outstanding() < 64;
  }
  void submit_reserved(BackendRequest request) override {
    if (outstanding() >= 64)
      throw std::logic_error("test backend outstanding overflow");
    staged_.push_back(std::move(request));
  }
  std::size_t response_count(std::uint32_t id) const noexcept override {
    return id == 1 ? responses_.size() : 0;
  }
  const BackendResponse &response_at(std::uint32_t, std::size_t i) const override {
    return responses_.at(i);
  }
  const BackendResponse &staged_response_at(std::uint32_t,
                                           std::size_t i) const override {
    return retired_.empty() ? responses_.at(selection_.at(i)) : retired_.at(i);
  }
  bool stage_pop_responses(std::uint32_t id, std::size_t count) override {
    std::vector<std::size_t> indices(count);
    std::iota(indices.begin(), indices.end(), 0);
    return stage_select_responses(id, indices);
  }
  void enable_independent_response_channels(std::uint32_t) override {}
  bool stage_select_responses(std::uint32_t id,
                              std::span<const std::size_t> indices) override {
    if (id != 1 || !selection_.empty() ||
        !detail::valid_response_selection(indices, responses_.size()))
      return false;
    selection_.assign(indices.begin(), indices.end());
    return true;
  }
  std::size_t outstanding() const noexcept override {
    return pending_.size() + staged_.size();
  }
  std::size_t outstanding_for(std::uint32_t id) const noexcept override {
    return id == 1 ? outstanding() : 0;
  }
  void prepare(const CycleContext &context) override {
    retired_.clear();
    for (auto it = pending_.begin(); it != pending_.end();) {
      if (it->due > context.domain_cycle || responses_.size() == 8) {
        ++it;
        continue;
      }
      const auto &request = it->request;
      responses_.push_back({.initiator_id = 1,
                            .request_id = request.request_id,
                            .success = true,
                            .read_data = complete_read_payload(request),
                            .operation = MemoryOperation::kRead});
      completion_order.push_back(request.address);
      notify_response_available(1);
      it = pending_.erase(it);
    }
  }
  void evaluate(const CycleContext &) override {}
  void commit(const CycleContext &context) override {
    if (!selection_.empty()) {
      detail::retire_selected_responses(responses_, selection_, retired_);
      selection_.clear();
    }
    for (auto &request : staged_) {
      record_accepted_request(request);
      const auto delay = (request.address / 64) % 32 == 0 ? 80 : 2;
      pending_.push_back({std::move(request), context.domain_cycle + delay});
    }
    staged_.clear();
  }
  std::vector<std::uint64_t> completion_order;

 private:
  struct Pending {
    BackendRequest request;
    std::uint64_t due;
  };
  std::deque<Pending> pending_;
  std::vector<BackendRequest> staged_;
  std::deque<BackendResponse> responses_;
  std::vector<BackendResponse> retired_;
  std::vector<std::size_t> selection_;
};

inline std::uint64_t check_reordered_reads(std::size_t capacity,
                                          bool independent, bool reverse,
                                          std::size_t issue_width) {
  Scheduler scheduler;
  const auto clock = scheduler.add_clock_mhz("core", 150);
  ReorderedReads backend(clock);
  FixedAxiPort port("read", clock,
                    FixedAxiPortConfig{.memory_channels = 1,
                                       .channel = 0,
                                       .initiator_id = 1,
                                       .max_burst_beats = 16,
                                       .read_beat_fifo_depth = 1,
                                       .read_reorder_capacity = capacity,
                                       .stream_read_beats = true,
                                       .max_pending_requests = 2,
                                       .max_outstanding_bursts = 16,
                                       .beat_issues_per_cycle = issue_width,
                                       .independent_read_write = independent},
                    backend);
  // A long parent spans many bursts; a held consumer also exhausts credits.
  constexpr std::size_t bytes = 16384;
  std::vector<std::uint8_t> payload(bytes);
  for (std::size_t i = 0; i < bytes; ++i)
    payload[i] = static_cast<std::uint8_t>(i / 64);
  backend.initialize_payload(0, 0, payload);
  std::vector<Component *> parts{&backend, &port.requests(), &port.responses(),
                                &port.read_beats(), &port.master()};
  if (reverse)
    std::reverse(parts.begin(), parts.end());
  for (auto *part : parts)
    scheduler.add_component(*part);
  if (!port.requests().try_push({.transaction_id = 19,
                                .address = 0,
                                .bytes = bytes,
                                .stream_read_beats = true,
                                .write_data = {}}))
    throw std::logic_error("test read enqueue failed");
  std::size_t received = 0;
  bool acknowledged = false;
  std::uint64_t end = 0;
  for (std::uint64_t cycle = 0; cycle < 30000; ++cycle) {
    if (cycle >= 120) {
      AxiReadBeatResponse beat;
      if (port.read_beats().try_pop(beat)) {
        if (!beat.success || beat.transaction_id != 19 ||
            beat.parent_offset != received * 64 ||
            beat.last != (received + 1 == bytes / 64) ||
            beat.read_data != std::vector<std::uint8_t>(
                                  64, static_cast<std::uint8_t>(received)))
          throw std::logic_error("reordered test stream differs");
        ++received;
      }
    }
    AxiResponse response;
    if (port.responses().try_pop(response)) {
      if (acknowledged || !response.success || response.transaction_id != 19 ||
          response.read_data != payload)
        throw std::logic_error("reordered test parent differs");
      acknowledged = true;
    }
    scheduler.step();
    if (port.master().reserved_read_beats() > capacity)
      throw std::logic_error("finite read reservations exceeded capacity");
    if (acknowledged && received == bytes / 64 && port.idle()) {
      end = cycle + 1;
      break;
    }
  }
  const auto &stats = port.master().stats();
  if (!end || stats.beats_issued != bytes / 64 ||
      stats.beats_completed != stats.beats_issued ||
      stats.read_beats_streamed != stats.beats_issued ||
      stats.requests_accepted != 1 || stats.requests_completed != 1 ||
      !stats.read_issue_credit_stalls || port.master().reserved_read_beats() ||
      backend.outstanding() || backend.response_count(1))
    throw std::logic_error("reordered test did not drain or conserve");
  if (capacity > 1 && std::is_sorted(backend.completion_order.begin(),
                                    backend.completion_order.end()))
    throw std::logic_error("test did not exercise out-of-order returns");
  for (auto *part : parts)
    scheduler.remove_component(*part);
  return end;
}
} // namespace axi_test
