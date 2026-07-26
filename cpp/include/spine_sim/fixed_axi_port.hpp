#pragma once

#include <cstddef>
#include <cstdint>
#include <stdexcept>
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
  std::uint32_t data_width_bytes{64};
  std::uint32_t max_burst_beats{16};
  std::size_t request_fifo_depth{32};
  std::size_t response_fifo_depth{32};
  std::size_t read_beat_fifo_depth{32};
  std::size_t read_reorder_capacity{32};
  bool stream_read_beats{};
  std::size_t max_pending_requests{32};
  std::size_t max_outstanding_bursts{32};
  std::size_t address_accepts_per_cycle{1};
  std::size_t beat_issues_per_cycle{1};
  std::size_t response_beats_per_cycle{4};
  std::uint64_t read_address_pipeline_cycles{};
  std::uint64_t read_data_pipeline_cycles{};
  std::uint64_t write_buffer_pipeline_cycles{};
  bool serialize_write_bursts{};
  AxiPeriodicStall read_address_stall{};
  AxiPeriodicStall write_address_stall{};
  AxiPeriodicStall write_data_stall{};
  AxiPeriodicStall read_response_stall{};
  AxiPeriodicStall write_response_stall{};
  std::size_t burst_trace_limit{};
  std::size_t beat_trace_limit{};
};

class FixedAxiPort {
 public:
  FixedAxiPort(std::string name, ClockId clock_id,
               const FixedAxiPortConfig &config, MemoryBackend &backend)
      : requests_(name + "-requests", clock_id, config.request_fifo_depth),
        responses_(name + "-responses", clock_id, config.response_fifo_depth),
        read_beats_(name + "-read-beats", clock_id,
                    config.read_beat_fifo_depth),
        master_(
            std::move(name), clock_id,
            AxiConfig{
                .initiator_id = config.initiator_id,
                .data_width_bytes = config.data_width_bytes,
                .max_burst_beats = config.max_burst_beats,
                .channels = config.memory_channels,
                .channel_interleave_bytes = 64,
                .max_pending_requests = config.max_pending_requests,
                .max_outstanding_bursts = config.max_outstanding_bursts,
                .address_accepts_per_cycle = config.address_accepts_per_cycle,
                .beat_issues_per_cycle = config.beat_issues_per_cycle,
                .response_beats_per_cycle = config.response_beats_per_cycle,
                .read_reorder_capacity = config.read_reorder_capacity,
                .read_address_pipeline_cycles =
                    config.read_address_pipeline_cycles,
                .read_data_pipeline_cycles = config.read_data_pipeline_cycles,
                .write_buffer_pipeline_cycles =
                    config.write_buffer_pipeline_cycles,
                .serialize_write_bursts = config.serialize_write_bursts,
                .read_address_stall = config.read_address_stall,
                .write_address_stall = config.write_address_stall,
                .write_data_stall = config.write_data_stall,
                .read_response_stall = config.read_response_stall,
                .write_response_stall = config.write_response_stall,
                .burst_trace_limit = config.burst_trace_limit,
                .beat_trace_limit = config.beat_trace_limit,
                .fixed_channel = config.channel,
            },
            requests_, responses_, backend,
            config.stream_read_beats ? &read_beats_ : nullptr),
        backend_(backend), channel_(config.channel),
        stream_read_beats_(config.stream_read_beats) {}

  void register_components(Scheduler &scheduler) {
    scheduler.add_component(requests_);
    scheduler.add_component(master_);
    scheduler.add_component(responses_);
    scheduler.add_component(read_beats_);
  }

  void unregister_components(Scheduler &scheduler) {
    if (!idle()) {
      throw std::logic_error("cannot unregister a busy fixed AXI port");
    }
    scheduler.remove_component(read_beats_);
    scheduler.remove_component(responses_);
    scheduler.remove_component(master_);
    scheduler.remove_component(requests_);
  }

  [[nodiscard]] Fifo<AxiRequest> &requests() noexcept { return requests_; }
  [[nodiscard]] const Fifo<AxiRequest> &requests() const noexcept {
    return requests_;
  }
  [[nodiscard]] Fifo<AxiResponse> &responses() noexcept { return responses_; }
  [[nodiscard]] Fifo<AxiReadBeatResponse> &read_beats() noexcept {
    return read_beats_;
  }
  [[nodiscard]] bool read_beat_stream_enabled() const noexcept {
    return stream_read_beats_;
  }
  [[nodiscard]] AxiMaster &master() noexcept { return master_; }
  [[nodiscard]] const AxiMaster &master() const noexcept { return master_; }
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
    return requests_.empty() && responses_.empty() && read_beats_.empty() &&
           master_.idle();
  }

 private:
  Fifo<AxiRequest> requests_;
  Fifo<AxiResponse> responses_;
  Fifo<AxiReadBeatResponse> read_beats_;
  AxiMaster master_;
  MemoryBackend& backend_;
  std::size_t channel_{};
  bool stream_read_beats_{};
};

}  // namespace spine::sim
