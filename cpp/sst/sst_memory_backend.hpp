#pragma once

#include <cstddef>
#include <cstdint>
#include <deque>
#include <memory>
#include <optional>
#include <string>
#include <unordered_map>
#include <vector>

#include "direct_dramsim3_engine.hpp"
#include "physical_hbm_mapper.hpp"
#include "spine_sim/memory_backend.hpp"
#include "sst/core/interfaces/stdMem.h"

namespace spine::sim::sst_adapter {

class SstMemoryBackend final : public MemoryBackend {
  struct InitiatorState;

public:
  SstMemoryBackend(
      ClockId clock_id, std::vector<SST::Interfaces::StandardMem *> interfaces,
      std::uint64_t channel_capacity_bytes,
      std::size_t accepts_per_channel_per_cycle,
      std::size_t max_outstanding_per_channel, std::size_t response_queue_depth,
      std::string address_mapping_mode = {},
      std::string address_mapping_table = {},
      std::size_t interleave_first_channel = 0,
      std::size_t interleave_channels = 0, std::uint64_t interleave_bytes = 64,
      std::unique_ptr<DirectDramSim3Engine> direct_engine = nullptr);

  bool try_reserve(const BackendRequestHeader &request) override;

  void submit_reserved(BackendRequest request) override;

  [[nodiscard]] bool
  reservation_intent_pending(std::uint32_t initiator_id,
                             std::size_t channel) const noexcept override;

  void account_same_cycle_reservation_stalls(std::uint32_t initiator_id,
                                             std::size_t channel,
                                             std::uint64_t count) override;

  [[nodiscard]] std::size_t
  response_count(std::uint32_t initiator_id) const noexcept override;

  [[nodiscard]] const BackendResponse &
  response_at(std::uint32_t initiator_id, std::size_t index) const override;

  [[nodiscard]] const BackendResponse &
  staged_response_at(std::uint32_t initiator_id,
                     std::size_t index) const override;

  bool stage_pop_responses(std::uint32_t initiator_id,
                           std::size_t count) override;

  [[nodiscard]] std::size_t outstanding() const noexcept override;

  [[nodiscard]] std::size_t
  outstanding_for(std::uint32_t initiator_id) const noexcept override;

  [[nodiscard]] bool has_dynamic_prepare_guard() const noexcept override;
  [[nodiscard]] bool has_dynamic_commit_guard() const noexcept override;
  [[nodiscard]] bool prepare_ready() const noexcept override;
  [[nodiscard]] bool commit_ready() const noexcept override;

  void prepare(const CycleContext &) override;

  void evaluate(const CycleContext &) override;

  void commit(const CycleContext &) override;

  void on_response(SST::Interfaces::StandardMem::Request *request);

  void advance_direct_to(std::uint64_t time_ps);

  void print_direct_stats();

  [[nodiscard]] const char *backend_label() const noexcept;

  [[nodiscard]] std::uint64_t accepted() const noexcept;
  [[nodiscard]] std::uint64_t submit_stalls() const noexcept;
  [[nodiscard]] std::uint64_t response_queue_stalls() const noexcept;
  [[nodiscard]] std::size_t max_outstanding() const noexcept;
  [[nodiscard]] const RegisteredChannelArbiterStats &
  arbitration_stats() const noexcept;
  [[nodiscard]] std::string arbitration_json() const;

private:
  struct InitiatorState {
    std::deque<BackendResponse> responses;
    std::vector<BackendResponse> retired_responses;
    std::size_t staged_response_pop{};
    std::size_t staged_submissions{};
    std::size_t outstanding{};
  };

  [[nodiscard]] InitiatorState *
  find_initiator_state(std::uint32_t initiator_id) noexcept;

  [[nodiscard]] const InitiatorState *
  find_initiator_state(std::uint32_t initiator_id) const noexcept;

  InitiatorState &ensure_initiator_state(std::uint32_t initiator_id);

  struct Inflight {
    std::uint64_t backend_request_id{};
    std::uint32_t initiator_id{};
    std::size_t channel{};
    MemoryOperation operation{MemoryOperation::kRead};
    std::uint32_t bytes{};
    BackendRequest request;
  };

  [[nodiscard]] bool channel_active(std::size_t channel) const noexcept;

  void complete_inflight(const Inflight &inflight, bool success);

  [[nodiscard]] std::uint64_t allocate_direct_inflight(Inflight inflight);

  void release_direct_inflight(std::uint64_t token);

  std::vector<SST::Interfaces::StandardMem *> interfaces_;
  std::unique_ptr<DirectDramSim3Engine> direct_engine_;
  std::uint64_t channel_capacity_bytes_{};
  std::size_t accepts_per_channel_per_cycle_{};
  std::size_t max_outstanding_per_channel_{};
  std::size_t response_queue_depth_{};
  PhysicalHbmAddressMapper address_mapper_;
  std::vector<std::size_t> channel_outstanding_;
  std::vector<std::size_t> staged_channel_submissions_;
  RegisteredChannelArbiter arbiter_;
  std::vector<std::unique_ptr<InitiatorState>> initiator_states_;
  std::vector<std::uint32_t> active_staged_initiators_;
  std::vector<std::uint32_t> active_response_pops_;
  std::vector<std::uint32_t> active_retired_initiators_;
  std::vector<BackendRequest> staged_submissions_;
  std::unordered_map<SST::Interfaces::StandardMem::Request::id_t, Inflight>
      inflight_;
  std::vector<std::optional<Inflight>> direct_inflight_;
  std::vector<std::size_t> free_direct_inflight_;
  std::vector<DirectDramSim3Engine::Completion> direct_completions_;
  std::deque<BackendResponse> external_arrivals_;
  std::uint64_t accepted_{};
  std::uint64_t submit_stalls_{};
  std::uint64_t response_queue_stalls_{};
  std::size_t max_outstanding_{};
  std::size_t direct_inflight_count_{};
  std::uint64_t direct_submit_time_ps_{};
};

} // namespace spine::sim::sst_adapter
