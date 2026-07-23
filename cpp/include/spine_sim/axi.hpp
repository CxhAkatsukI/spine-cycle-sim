#pragma once

#include <cstddef>
#include <cstdint>
#include <deque>
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
  std::vector<std::uint8_t> write_data;
};

struct AxiResponse {
  std::uint64_t transaction_id{};
  MemoryOperation operation{MemoryOperation::kRead};
  bool success{true};
  std::vector<std::uint8_t> read_data;
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
  std::optional<std::size_t> fixed_channel;
};

struct AxiStats {
  std::uint64_t requests_accepted{};
  std::uint64_t requests_completed{};
  std::uint64_t request_queue_stalls{};
  std::uint64_t response_queue_stalls{};
  std::uint64_t bursts_accepted{};
  std::uint64_t beats_issued{};
  std::uint64_t beats_completed{};
  std::uint64_t backend_submit_stalls{};
  std::uint64_t four_kib_splits{};
  std::uint64_t read_bytes{};
  std::uint64_t write_bytes{};
  std::uint64_t zero_filled_write_bytes{};
  std::size_t max_outstanding_bursts{};
};

class AxiMaster final : public Component {
 public:
  AxiMaster(std::string name, ClockId clock_id, AxiConfig config,
            Fifo<AxiRequest>& requests, Fifo<AxiResponse>& responses,
            MemoryBackend& backend);

  [[nodiscard]] const AxiStats& stats() const noexcept { return stats_; }
  [[nodiscard]] std::size_t pending_requests() const noexcept;
  [[nodiscard]] std::size_t outstanding_bursts() const noexcept {
    return active_bursts_.size();
  }
  [[nodiscard]] bool idle() const noexcept;

  void evaluate(const CycleContext& context) override;
  void commit(const CycleContext& context) override;

 private:
  struct Parent {
    AxiRequest request;
    std::size_t total_bursts{};
    std::size_t completed_bursts{};
    bool success{true};
    std::vector<std::uint8_t> read_data;
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
  };

  struct StagedBeat {
    std::uint64_t burst_id{};
    std::uint64_t parent_offset{};
    BackendRequest request;
  };

  struct BackendMapping {
    std::uint64_t burst_id{};
    std::uint64_t parent_offset{};
    std::uint32_t bytes{};
  };

  struct ReadyResponse {
    std::uint64_t parent_id{};
    AxiResponse response;
  };

  [[nodiscard]] std::vector<Burst> split_request(
      std::uint64_t parent_id, const AxiRequest& request);
  [[nodiscard]] std::size_t channel_for(std::uint64_t address) const;
  [[nodiscard]] Burst* find_active(std::uint64_t burst_id);
  void reset_staging();
  void evaluate_output();
  void evaluate_backend_responses();
  void evaluate_request_input();
  void evaluate_address_channel();
  void evaluate_data_channel();
  void commit_backend_responses();
  void commit_request_input();
  void commit_address_channel();
  void commit_data_channel();
  void commit_output();

  AxiConfig config_;
  Fifo<AxiRequest>& requests_;
  Fifo<AxiResponse>& responses_;
  MemoryBackend& backend_;

  std::uint64_t next_parent_id_{};
  std::uint64_t next_burst_id_{};
  std::uint64_t next_backend_id_{};
  std::unordered_map<std::uint64_t, Parent> parents_;
  std::deque<Burst> pending_address_;
  std::vector<Burst> active_bursts_;
  std::unordered_map<std::uint64_t, BackendMapping> backend_mappings_;
  std::deque<ReadyResponse> ready_responses_;
  std::size_t issue_round_robin_{};

  std::optional<AxiRequest> staged_input_;
  std::uint64_t staged_parent_id_{};
  std::vector<Burst> staged_new_bursts_;
  std::vector<std::uint64_t> staged_address_bursts_;
  std::vector<StagedBeat> staged_beats_;
  std::vector<BackendResponse> staged_backend_responses_;
  bool staged_output_{};
  AxiStats stats_;
};

}  // namespace spine::sim
