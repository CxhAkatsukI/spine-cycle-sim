#pragma once

#include <cstddef>
#include <cstdint>
#include <functional>
#include <string>
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

class Scheduler {
 public:
  ClockId add_clock_mhz(std::string name, double frequency_mhz,
                        TimestampFs phase_fs = 0);
  void add_component(Component& component);

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

 private:
  std::vector<ClockDomainSnapshot> clocks_;
  std::vector<Component*> components_;
  TimestampFs now_fs_{};
  std::uint64_t event_count_{};
};

}  // namespace spine::sim
