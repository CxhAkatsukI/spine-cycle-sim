#pragma once

#include <array>
#include <cstddef>
#include <cstdint>
#include <deque>
#include <memory>
#include <span>
#include <stdexcept>
#include <string>
#include <unordered_map>
#include <unordered_set>
#include <vector>

#include "spine_sim/component.hpp"

namespace spine::sim {

enum class MemoryOperation { kRead, kWrite };

struct BackendRequest {
  std::uint32_t initiator_id{};
  std::uint64_t request_id{};
  std::size_t channel{};
  MemoryOperation operation{MemoryOperation::kRead};
  std::uint64_t address{};
  std::uint32_t bytes{};
  std::vector<std::uint8_t> write_data;
};

struct BackendRequestHeader {
  std::uint32_t initiator_id{};
  std::uint64_t request_id{};
  std::size_t channel{};
  MemoryOperation operation{MemoryOperation::kRead};
  std::uint64_t address{};
  std::uint32_t bytes{};
};

struct BackendResponse {
  std::uint32_t initiator_id{};
  std::uint64_t request_id{};
  bool success{true};
  std::vector<std::uint8_t> read_data;
};

struct MemoryLocalityStats {
  std::uint64_t requests{};
  std::uint64_t bytes{};
  std::uint64_t first_requests{};
  std::uint64_t first_bytes{};
  std::uint64_t contiguous_requests{};
  std::uint64_t contiguous_bytes{};
  std::uint64_t repeated_requests{};
  std::uint64_t repeated_bytes{};
  std::uint64_t discontinuous_requests{};
  std::uint64_t discontinuous_bytes{};
};

struct MemoryTrafficStats {
  MemoryLocalityStats reads;
  MemoryLocalityStats writes;
};

[[nodiscard]] MemoryLocalityStats combine_memory_traffic(
    const MemoryTrafficStats& stats) noexcept;
[[nodiscard]] MemoryTrafficStats subtract_memory_traffic(
    const MemoryTrafficStats& after, const MemoryTrafficStats& before);

class MemoryBackend : public Component {
 public:
  using Component::Component;

  [[nodiscard]] bool has_prepare_phase() const noexcept override {
    return true;
  }
  [[nodiscard]] bool has_evaluate_phase() const noexcept override {
    return false;
  }

  void register_initiator(std::uint32_t initiator_id);
  void initialize_payload(std::size_t channel, std::uint64_t address,
                          const std::vector<std::uint8_t>& data);
  void fill_payload(std::size_t channel, std::uint64_t address,
                    std::uint64_t bytes, std::uint8_t value);
  [[nodiscard]] std::vector<std::uint8_t> inspect_payload(
      std::size_t channel, std::uint64_t address, std::size_t bytes) const;
  bool try_submit(const BackendRequest& request);
  // A caller that owns an expensive write payload may reserve admission from
  // the header first, then move the complete request immediately. This is one
  // evaluate-phase operation; reservations must not be retained by callers.
  virtual bool try_reserve(const BackendRequestHeader& request) = 0;
  virtual void submit_reserved(BackendRequest request) = 0;
  // Registered arbitration state cannot change until the global commit
  // phase. Fixed-channel AXI masters can collapse additional same-cycle
  // retries while retaining every observable stall counter.
  [[nodiscard]] virtual bool reservation_intent_pending(
      std::uint32_t initiator_id, std::size_t channel) const noexcept {
    (void)initiator_id;
    (void)channel;
    return false;
  }
  virtual void account_same_cycle_reservation_stalls(
      std::uint32_t initiator_id, std::size_t channel,
      std::uint64_t count) {
    (void)initiator_id;
    (void)channel;
    if (count != 0) {
      throw std::logic_error(
          "backend cannot account coalesced reservation stalls");
    }
  }
  [[nodiscard]] virtual std::size_t response_count(
      std::uint32_t initiator_id) const noexcept = 0;
  [[nodiscard]] virtual const BackendResponse& response_at(
      std::uint32_t initiator_id, std::size_t index) const = 0;
  virtual bool stage_pop_responses(std::uint32_t initiator_id,
                                   std::size_t count) = 0;
  [[nodiscard]] virtual std::size_t outstanding() const noexcept = 0;
  [[nodiscard]] virtual std::size_t outstanding_for(
      std::uint32_t initiator_id) const noexcept = 0;
  [[nodiscard]] const MemoryTrafficStats& traffic_stats() const noexcept {
    return traffic_stats_;
  }
  [[nodiscard]] const std::unordered_map<std::uint32_t, MemoryTrafficStats>&
  traffic_stats_by_initiator() const noexcept {
    return traffic_stats_by_initiator_;
  }
  void begin_traffic_epoch() noexcept;

 protected:
  [[nodiscard]] bool initiator_registered(
      std::uint32_t initiator_id) const noexcept;
  void commit_write_payload(const BackendRequest& request);
  [[nodiscard]] std::vector<std::uint8_t> complete_read_payload(
      const BackendRequest& request) const;
 void record_accepted_request(const BackendRequest& request);

 private:
  static constexpr std::size_t kPayloadPageBytes = 4096;
  static constexpr std::size_t kPayloadValidityWords = kPayloadPageBytes / 64;

  struct PayloadPage {
    std::array<std::uint8_t, kPayloadPageBytes> bytes{};
    std::array<std::uint64_t, kPayloadValidityWords> validity{};

    [[nodiscard]] bool contains(std::size_t offset) const noexcept {
      return (validity[offset / 64] & (std::uint64_t{1} << (offset % 64))) != 0;
    }
    void mark(std::size_t offset) noexcept {
      validity[offset / 64] |= std::uint64_t{1} << (offset % 64);
    }
  };

  struct AccessCursor {
    bool valid{};
    std::size_t channel{};
    std::uint64_t address{};
    std::uint32_t bytes{};
  };

  struct InitiatorCursors {
    std::array<AccessCursor, 2> operations;
  };

  struct FillRegion {
    std::uint64_t address{};
    std::uint64_t bytes{};
    std::uint8_t value{};
  };

  std::unordered_set<std::uint32_t> initiators_;
  std::unordered_map<std::size_t,
                     std::unordered_map<std::uint64_t, PayloadPage>>
      payload_storage_;
  std::unordered_map<std::size_t, std::vector<FillRegion>> payload_fills_;
  MemoryTrafficStats traffic_stats_;
  std::unordered_map<std::uint32_t, MemoryTrafficStats>
      traffic_stats_by_initiator_;
  std::unordered_map<std::uint32_t, InitiatorCursors> traffic_cursors_;
};

struct RegisteredChannelArbiterStats {
  std::uint64_t unique_intents{};
  std::uint64_t request_waits{};
  std::uint64_t grants{};
  std::uint64_t consumed_grants{};
  std::uint64_t contended_cycles{};
  std::uint64_t contention_losers{};
  std::uint64_t capacity_blocked_cycles{};
  std::size_t max_contenders{};
  std::size_t max_pending_grants{};
};

// Requests are collected during evaluate and granted during commit for
// consumption on the next cycle. This removes component-order priority.
class RegisteredChannelArbiter {
 public:
  RegisteredChannelArbiter(std::size_t channels,
                           std::size_t grants_per_channel_per_cycle);

  [[nodiscard]] bool try_acquire(const BackendRequest& request);
  [[nodiscard]] bool try_acquire(const BackendRequestHeader& request);
  void arbitrate(std::span<const std::size_t> channel_outstanding,
                 std::size_t max_outstanding_per_channel);
  [[nodiscard]] std::size_t pending_intents() const noexcept;
  [[nodiscard]] std::size_t pending_grants() const noexcept;
  [[nodiscard]] std::size_t pending_grants_for(
      std::uint32_t initiator_id) const noexcept;
  [[nodiscard]] bool intent_pending(std::uint32_t initiator_id,
                                    std::size_t channel) const noexcept;
  void account_duplicate_waits(std::uint32_t initiator_id,
                               std::size_t channel, std::uint64_t count);
  [[nodiscard]] const RegisteredChannelArbiterStats& stats() const noexcept {
    return stats_;
  }

 private:
  std::size_t channels_{};
  std::size_t grants_per_channel_per_cycle_{};
  // HBM profiles expose at most 32 pseudo-channels. Keep per-initiator
  // channel state in bitmasks so repeated blocked AXI attempts do not pay for
  // ordered-map lookup or copy an unused BackendRequest payload.
  std::vector<std::vector<std::uint32_t>> intents_;
  std::vector<std::size_t> grants_by_channel_;
  std::vector<std::uint32_t> next_initiator_;
  std::unordered_map<std::uint32_t, std::uint64_t> intent_masks_;
  std::unordered_map<std::uint32_t, std::uint64_t> grant_masks_;
  std::uint64_t active_intent_channels_{};
  std::size_t pending_intent_count_{};
  std::size_t pending_grant_count_{};
  RegisteredChannelArbiterStats stats_;
};

struct MockMemoryConfig {
  std::size_t channels{};
  std::uint64_t latency_cycles{};
  std::size_t accepts_per_channel_per_cycle{};
  std::size_t max_outstanding_per_channel{};
  std::size_t response_queue_depth{};
  bool registered_round_robin_arbitration{};
};

struct MockMemoryStats {
  std::uint64_t accepted{};
  std::uint64_t submit_stalls{};
  std::uint64_t response_queue_stalls{};
  std::size_t max_outstanding{};
};

class MockMemoryBackend final : public MemoryBackend {
 public:
  MockMemoryBackend(std::string name, ClockId clock_id, MockMemoryConfig config);

  bool try_reserve(const BackendRequestHeader& request) override;
  void submit_reserved(BackendRequest request) override;
  [[nodiscard]] bool reservation_intent_pending(
      std::uint32_t initiator_id,
      std::size_t channel) const noexcept override;
  void account_same_cycle_reservation_stalls(
      std::uint32_t initiator_id, std::size_t channel,
      std::uint64_t count) override;
  [[nodiscard]] std::size_t response_count(
      std::uint32_t initiator_id) const noexcept override;
  [[nodiscard]] const BackendResponse& response_at(
      std::uint32_t initiator_id, std::size_t index) const override;
  bool stage_pop_responses(std::uint32_t initiator_id,
                           std::size_t count) override;
  [[nodiscard]] std::size_t outstanding() const noexcept override;
  [[nodiscard]] std::size_t outstanding_for(
      std::uint32_t initiator_id) const noexcept override;
  [[nodiscard]] const MockMemoryStats& stats() const noexcept { return stats_; }
  [[nodiscard]] const RegisteredChannelArbiterStats* arbitration_stats()
      const noexcept {
    return arbiter_ == nullptr ? nullptr : &arbiter_->stats();
  }

  void prepare(const CycleContext& context) override;
  void evaluate(const CycleContext&) override {}
  void commit(const CycleContext& context) override;

 private:
  struct Pending {
    BackendRequest request;
    std::size_t channel{};
    std::uint64_t due_cycle{};
    bool completed{};
  };

  [[nodiscard]] std::size_t channel_outstanding(std::size_t channel) const;

  MockMemoryConfig config_;
  std::unique_ptr<RegisteredChannelArbiter> arbiter_;
  std::deque<Pending> pending_;
  std::unordered_map<std::uint32_t, std::deque<BackendResponse>> responses_;
  std::vector<BackendRequest> staged_submissions_;
  std::unordered_map<std::uint32_t, std::size_t> staged_response_pops_;
  MockMemoryStats stats_;
};

}  // namespace spine::sim
