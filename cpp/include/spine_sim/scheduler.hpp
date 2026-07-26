#pragma once

#include <cstddef>
#include <cstdint>
#include <functional>
#include <string>
#include <unordered_map>
#include <vector>

#include "spine_sim/component.hpp"

namespace spine::sim {

struct ClockDomainSnapshot {
  std::string name;
  TimestampFs period_fs{};
  TimestampFs phase_fs{};
  TimestampFs next_edge_fs{};
  std::uint64_t completed_cycles{};
};

struct SchedulerComponentProfile {
  std::string name;
  std::uint64_t prepare_samples{};
  std::uint64_t prepare_nanoseconds{};
  std::uint64_t evaluate_samples{};
  std::uint64_t evaluate_nanoseconds{};
  std::uint64_t commit_samples{};
  std::uint64_t commit_nanoseconds{};
};

class Scheduler {
 public:
  Scheduler();
  ~Scheduler();

  ClockId add_clock_mhz(std::string name, double frequency_mhz,
                        TimestampFs phase_fs = 0);
  void add_component(Component& component);
  void remove_component(Component& component);

  void step();
  void run_events(std::uint64_t event_count);
  void run_until(const std::function<bool()>& stop,
                 std::uint64_t max_events);

  [[nodiscard]] TimestampFs now_fs() const noexcept { return now_fs_; }
  [[nodiscard]] std::uint64_t event_count() const noexcept {
    return event_count_;
  }
  [[nodiscard]] const ClockDomainSnapshot& clock(ClockId id) const;
  [[nodiscard]] std::size_t clock_count() const noexcept {
    return clocks_.size();
  }
  [[nodiscard]] std::size_t component_count() const noexcept {
    return components_.size();
  }
  [[nodiscard]] std::uint64_t profiling_period() const noexcept {
    return profiling_period_;
  }
  [[nodiscard]] std::vector<SchedulerComponentProfile> component_profile()
      const;

 private:
  enum class ProfilePhase { kPrepare, kEvaluate, kCommit };

  void record_profile(Component& component, ProfilePhase phase,
                      std::uint64_t nanoseconds);

  std::vector<ClockDomainSnapshot> clocks_;
  std::vector<Component*> components_;
  std::vector<Component*> prepare_components_;
  std::vector<Component*> evaluate_components_;
  std::vector<bool> evaluate_dynamic_guards_;
  std::vector<Component*> commit_components_;
  std::vector<bool> commit_dynamic_guards_;
  std::vector<bool> commit_latched_guards_;
  std::vector<bool> commit_readiness_;
  std::unordered_map<Component*, SchedulerComponentProfile> profiles_;
  std::uint64_t profiling_period_{};
  bool emit_profile_report_{};
  TimestampFs now_fs_{};
  std::uint64_t event_count_{};
};

}  // namespace spine::sim
