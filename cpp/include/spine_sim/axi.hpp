#pragma once

#include <cstddef>
#include <cstdint>
#include <deque>
#include <map>
#include <optional>
#include <string>
#include <unordered_map>
#include <vector>

#include "spine_sim/component.hpp"
#include "spine_sim/fifo.hpp"
#include "spine_sim/memory_backend.hpp"

namespace spine::sim {

struct AxiRequest {
  std::uint64_t transaction_id{};
  MemoryOperation operation{MemoryOperation::kRead};
  std::uint64_t address{};
  std::uint64_t bytes{};
  bool stream_read_beats{};
  std::vector<std::uint8_t> write_data;
};

struct AxiResponse {
  std::uint64_t transaction_id{};
  MemoryOperation operation{MemoryOperation::kRead};
  bool success{true};
  std::vector<std::uint8_t> read_data;
};

struct AxiReadBeatResponse {
  std::uint64_t transaction_id{};
  std::uint64_t address{};
  std::uint64_t parent_offset{};
  bool success{true};
  bool last{};
  std::vector<std::uint8_t> read_data;
};

struct AxiPeriodicStall {
  std::uint64_t period_cycles{};
  std::uint64_t stall_cycles{};
  std::uint64_t phase_cycles{};

  [[nodiscard]] bool valid() const noexcept {
    return (period_cycles == 0 && stall_cycles == 0) ||
           (period_cycles != 0 && stall_cycles < period_cycles);
  }
  [[nodiscard]] bool stalled(std::uint64_t cycle) const noexcept {
    if (period_cycles == 0) {
      return false;
    }
    const std::uint64_t cycle_mod = cycle % period_cycles;
    const std::uint64_t phase_mod = phase_cycles % period_cycles;
    const std::uint64_t position =
        cycle_mod < period_cycles - phase_mod
            ? cycle_mod + phase_mod
            : cycle_mod - (period_cycles - phase_mod);
    return position < stall_cycles;
  }
};

struct AxiConfig {
  std::uint32_t initiator_id{};
  std::uint32_t data_width_bytes{};
  std::uint32_t max_burst_beats{};
  std::size_t channels{};
  std::uint64_t channel_interleave_bytes{};
  std::size_t max_pending_requests{};
  std::size_t max_outstanding_bursts{};
  std::size_t address_accepts_per_cycle{};
  std::size_t beat_issues_per_cycle{};
  std::size_t response_beats_per_cycle{};
  std::size_t read_reorder_capacity{32};
  // Generated Vitis adapters pipeline read addresses and buffer write data
  // before exposing an external burst. Zero preserves the generic core.
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
  std::optional<std::size_t> fixed_channel;
};

struct AxiBurstTrace {
  std::uint64_t transaction_id{};
  MemoryOperation operation{MemoryOperation::kRead};
  std::uint64_t address{};
  std::uint64_t bytes{};
  std::size_t beats{};
  std::uint64_t parent_accept_cycle{};
  std::uint64_t address_issue_cycle{};
};

struct AxiBeatTrace {
  std::uint64_t backend_request_id{};
  std::uint64_t transaction_id{};
  MemoryOperation operation{MemoryOperation::kRead};
  std::uint64_t address{};
  std::uint32_t bytes{};
  std::uint64_t issue_cycle{};
  std::uint64_t completion_cycle{};
};

struct AxiStats {
  std::uint64_t requests_accepted{};
  std::uint64_t requests_completed{};
  std::uint64_t request_queue_stalls{};
  std::uint64_t response_queue_stalls{};
  std::uint64_t read_beat_queue_stalls{};
  std::uint64_t read_reorder_stalls{};
  std::uint64_t read_data_pipeline_stalls{};
  std::uint64_t read_beats_streamed{};
  std::uint64_t bursts_accepted{};
  std::uint64_t beats_issued{};
  std::uint64_t beats_completed{};
  std::uint64_t backend_submit_stalls{};
  std::uint64_t address_pipeline_stalls{};
  std::uint64_t write_burst_serialization_stalls{};
  std::uint64_t read_address_channel_stalls{};
  std::uint64_t write_address_channel_stalls{};
  std::uint64_t write_data_channel_stalls{};
  std::uint64_t read_response_channel_stalls{};
  std::uint64_t write_response_channel_stalls{};
  std::uint64_t four_kib_splits{};
  std::uint64_t read_bytes{};
  std::uint64_t write_bytes{};
  std::uint64_t zero_filled_write_bytes{};
  std::size_t max_outstanding_bursts{};
  std::uint64_t burst_trace_dropped{};
  std::uint64_t beat_trace_dropped{};
};

void accumulate_axi_stats(AxiStats &total, const AxiStats &sample) noexcept;

class AxiMaster final : public Component {
 public:
  AxiMaster(std::string name, ClockId clock_id, AxiConfig config,
            Fifo<AxiRequest> &requests, Fifo<AxiResponse> &responses,
            MemoryBackend &backend,
            Fifo<AxiReadBeatResponse> *read_beats = nullptr);

  [[nodiscard]] const AxiStats& stats() const noexcept { return stats_; }
  [[nodiscard]] const AxiConfig &config() const noexcept { return config_; }
  [[nodiscard]] std::size_t pending_requests() const noexcept;
  [[nodiscard]] std::size_t outstanding_bursts() const noexcept {
    return active_bursts_.size();
  }
  [[nodiscard]] bool idle() const noexcept;
  [[nodiscard]] const std::vector<AxiBurstTrace> &burst_trace() const noexcept {
    return burst_trace_;
  }
  [[nodiscard]] const std::vector<AxiBeatTrace> &beat_trace() const noexcept {
    return beat_trace_;
  }

  void evaluate(const CycleContext& context) override;
  void commit(const CycleContext& context) override;

 private:
  struct TimedReadBeat {
    AxiReadBeatResponse response;
    std::uint64_t ready_cycle{};
  };

  struct Parent {
    AxiRequest request;
    std::size_t total_bursts{};
    std::size_t completed_bursts{};
    bool success{true};
    std::vector<std::uint8_t> read_data;
    std::size_t stream_beats_expected{};
    std::size_t stream_beats_published{};
    std::uint64_t next_stream_offset{};
    std::map<std::uint64_t, TimedReadBeat> ready_stream_beats;
    bool memory_complete{};
    bool response_queued{};
  };

  struct Burst {
    std::uint64_t burst_id{};
    std::uint64_t parent_id{};
    MemoryOperation operation{MemoryOperation::kRead};
    std::uint64_t address{};
    std::uint64_t bytes{};
    std::uint64_t parent_offset{};
    std::size_t beats_total{};
    std::size_t beats_issued{};
    std::size_t beats_completed{};
    std::uint64_t parent_accept_cycle{};
    std::uint64_t address_ready_cycle{};
  };

  struct StagedBeat {
    std::uint64_t burst_id{};
    std::uint64_t parent_offset{};
    std::uint64_t issue_cycle{};
    BackendRequest request;
  };

  struct BackendMapping {
    std::uint64_t burst_id{};
    std::uint64_t parent_offset{};
    std::uint32_t bytes{};
    std::optional<std::size_t> trace_index;
  };

  struct ReadyResponse {
    std::uint64_t parent_id{};
    AxiResponse response;
  };

  [[nodiscard]] std::vector<Burst> split_request(
      std::uint64_t parent_id, const AxiRequest &request,
      std::uint64_t accepted_cycle);
  [[nodiscard]] std::size_t channel_for(std::uint64_t address) const;
  [[nodiscard]] Burst* find_active(std::uint64_t burst_id);
  void reset_staging();
  void evaluate_output();
  void evaluate_read_beat_output(const CycleContext &context);
  void evaluate_backend_responses(const CycleContext &context);
  void evaluate_request_input(const CycleContext &context);
  void evaluate_address_channel(const CycleContext &context);
  void evaluate_data_channel(const CycleContext &context);
  void commit_backend_responses(const CycleContext &context);
  void commit_request_input();
  void commit_address_channel(const CycleContext &context);
  void commit_data_channel();
  void commit_output();
  void commit_read_beat_output();
  void queue_parent_response_if_ready(std::uint64_t parent_id);
  [[nodiscard]] std::size_t read_reorder_occupancy() const noexcept;

  AxiConfig config_;
  Fifo<AxiRequest> &requests_;
  Fifo<AxiResponse> &responses_;
  MemoryBackend &backend_;
  Fifo<AxiReadBeatResponse> *read_beats_{};

  std::uint64_t next_parent_id_{};
  std::uint64_t next_burst_id_{};
  std::uint64_t next_backend_id_{};
  std::unordered_map<std::uint64_t, Parent> parents_;
  std::deque<Burst> pending_address_;
  std::vector<Burst> active_bursts_;
  std::unordered_map<std::uint64_t, BackendMapping> backend_mappings_;
  std::deque<ReadyResponse> ready_responses_;
  std::vector<AxiBurstTrace> burst_trace_;
  std::vector<AxiBeatTrace> beat_trace_;
  std::size_t issue_round_robin_{};

  std::optional<AxiRequest> staged_input_;
  std::uint64_t staged_parent_id_{};
  std::vector<Burst> staged_new_bursts_;
  std::vector<std::uint64_t> staged_address_bursts_;
  std::vector<StagedBeat> staged_beats_;
  std::vector<BackendResponse> staged_backend_responses_;
  std::optional<std::pair<std::uint64_t, std::uint64_t>>
      staged_read_beat_output_;
  bool staged_output_{};
  AxiStats stats_;
};

}  // namespace spine::sim
