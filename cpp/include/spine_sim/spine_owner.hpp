#pragma once

#include <cstddef>
#include <cstdint>
#include <deque>
#include <optional>
#include <string>
#include <unordered_map>
#include <vector>

#include "spine_sim/component.hpp"

namespace spine::sim {

struct SpineOwnerSchedulerConfig {
  std::size_t max_vertices{16'777'216};
  std::size_t partitions{16};
  std::size_t vertices_per_partition{1'048'576};
  std::size_t owner_fifo_depth{256};
  std::size_t reactivation_fifo_depth{256};
};

struct SpineOwnerKeyState {
  bool queued{};
  bool in_flight{};
  bool dirty{};

  friend bool operator==(const SpineOwnerKeyState &,
                         const SpineOwnerKeyState &) = default;
};

struct SpineOwnerSchedulerStats {
  std::uint64_t activation_attempts{};
  std::uint64_t initial_activations{};
  std::uint64_t reactivations{};
  std::uint64_t coalesced_activations{};
  std::uint64_t activation_backpressure_cycles{};
  std::uint64_t dispatches{};
  std::uint64_t completions{};
  std::uint64_t reactivation_requeues{};
  std::uint64_t ready_publications{};
  std::uint64_t deferred_reactivation_publications{};
  std::uint64_t owner_fifo_backpressure_cycles{};
  std::uint64_t reactivation_fifo_backpressure_cycles{};
  std::uint64_t work_credits_created{};
  std::uint64_t work_credits_retired{};
  std::uint64_t max_work_credits{};
  std::size_t max_owner_fifo_occupancy{};
  std::size_t max_reactivation_fifo_occupancy{};
  std::size_t max_ready_list_occupancy{};
  std::size_t max_deferred_reactivation_occupancy{};
};

struct SpineOwnerFrontierStats {
  std::uint64_t control_cycles{};
  std::uint64_t activation_attempts{};
  std::uint64_t activation_backpressure_cycles{};
  std::uint64_t completion_attempts{};
  std::uint64_t completion_backpressure_cycles{};
  std::uint64_t dispatch_attempts{};
  std::uint64_t dispatch_backpressure_cycles{};
  std::uint64_t frontiers_completed{};
  std::uint64_t frontiers_dispatched{};
};

// Device-owned per-key scheduling. External producers call try_activate during
// evaluate; consumers call try_dispatch/try_complete during evaluate. All state
// changes become visible only in commit.
class SpineOwnerScheduler final : public Component {
 public:
  SpineOwnerScheduler(std::string name, ClockId clock_id,
                      SpineOwnerSchedulerConfig config = {});

  [[nodiscard]] const SpineOwnerSchedulerConfig &config() const noexcept {
    return config_;
  }
  [[nodiscard]] const SpineOwnerSchedulerStats &stats() const noexcept {
    return stats_;
  }
  [[nodiscard]] std::size_t partition_for(std::uint32_t key) const;
  [[nodiscard]] SpineOwnerKeyState state(std::uint32_t key) const noexcept;
  [[nodiscard]] const std::uint32_t *owner_front(
      std::size_t partition) const;
  [[nodiscard]] std::size_t owner_size(std::size_t partition) const;
  [[nodiscard]] std::size_t reactivation_size(std::size_t partition) const;
  [[nodiscard]] std::size_t ready_size(std::size_t partition) const;
  [[nodiscard]] std::uint64_t work_credits() const noexcept {
    return work_credits_;
  }
  [[nodiscard]] bool quiescent() const noexcept;
  [[nodiscard]] bool ledger_closed() const noexcept;

  bool try_activate(std::uint32_t key);
  bool try_dispatch(std::size_t partition, std::uint32_t &key);
  bool try_complete(std::uint32_t key);

  void evaluate(const CycleContext &) override;
  void commit(const CycleContext &) override;

 private:
  enum class ActivationAction { kInitial, kReactivation, kCoalesced };
  enum class DispatchSource { kOwnerFifo, kReadyList };

  struct StagedActivation {
    std::uint32_t key{};
    std::size_t partition{};
    ActivationAction action{ActivationAction::kInitial};
  };

  struct StagedDispatch {
    std::uint32_t key{};
    DispatchSource source{DispatchSource::kOwnerFifo};
  };

  [[nodiscard]] SpineOwnerKeyState &mutable_state(std::uint32_t key);
  [[nodiscard]] std::size_t reserved_owner_enqueues(
      std::size_t partition) const noexcept;
  [[nodiscard]] std::uint64_t structural_credits() const noexcept;
  void update_maxima() noexcept;

  SpineOwnerSchedulerConfig config_;
  SpineOwnerSchedulerStats stats_;
  std::vector<std::deque<std::uint32_t>> owner_queues_;
  // The active list is bounded by the physical vertex domain and represents
  // device-published IDs resident in HBM between round relaunches. Keys remain
  // logically queued until dispatch; this preserves activation coalescing.
  std::vector<std::deque<std::uint32_t>> ready_queues_;
  std::vector<std::deque<std::uint32_t>> reactivation_queues_;
  std::vector<std::deque<std::uint32_t>> deferred_reactivation_queues_;
  std::unordered_map<std::uint32_t, SpineOwnerKeyState> states_;
  std::optional<StagedActivation> staged_activation_;
  std::vector<std::optional<StagedDispatch>> staged_dispatches_;
  std::vector<std::optional<std::uint32_t>> staged_completions_;
  std::vector<std::optional<std::uint32_t>> staged_requeues_;
  std::vector<std::optional<std::uint32_t>> staged_publications_;
  std::vector<std::optional<std::uint32_t>>
      staged_reactivation_publications_;
  std::uint64_t work_credits_{};
};

// Drives the round boundary around the per-key owner. It models device-owned
// frontier admission, completion, and dispatch while allowing the host to
// relaunch/re-bin an already selected frontier without recomputing membership.
class SpineOwnerFrontierController final : public Component {
 public:
  SpineOwnerFrontierController(std::string name, ClockId clock_id,
                               SpineOwnerScheduler &owner,
                               std::vector<std::uint32_t> initial_frontier,
                               const bool *payload_ready = nullptr);

  void restart(std::vector<std::uint32_t> completed_frontier,
               std::vector<std::uint32_t> next_frontier,
               bool admit_next);
  [[nodiscard]] bool ready() const noexcept { return ready_; }
  [[nodiscard]] const bool *ready_gate() const noexcept { return &ready_; }
  [[nodiscard]] bool failed() const noexcept { return failed_; }
  [[nodiscard]] const std::string &failure() const noexcept { return failure_; }
  [[nodiscard]] const SpineOwnerFrontierStats &stats() const noexcept {
    return stats_;
  }
  [[nodiscard]] const std::vector<std::uint32_t> &dispatched() const noexcept {
    return dispatched_;
  }

  void evaluate(const CycleContext &) override;
  void commit(const CycleContext &) override;

 private:
  enum class Phase { kComplete, kAdmit, kDispatch, kPayloadWait, kReady };

  void prepare_partitioned_completion();
  void validate_frontier() const;

  SpineOwnerScheduler &owner_;
  const bool *payload_ready_{};
  SpineOwnerFrontierStats stats_;
  std::vector<std::uint32_t> completed_frontier_;
  std::vector<std::uint32_t> next_frontier_;
  std::vector<std::uint32_t> dispatched_;
  std::vector<std::deque<std::uint32_t>> pending_completions_;
  std::size_t next_activation_{};
  std::size_t remaining_completions_{};
  std::size_t dispatch_partition_{};
  Phase phase_{Phase::kAdmit};
  bool staged_activation_{};
  std::vector<bool> staged_completions_;
  std::vector<std::optional<std::uint32_t>> staged_dispatches_;
  bool staged_phase_advance_{};
  bool ready_{};
  bool failed_{};
  std::string failure_;
};

}  // namespace spine::sim
