#include "spine_sim/scheduler.hpp"

#include <algorithm>
#include <cmath>
#include <limits>
#include <stdexcept>
#include <utility>

namespace spine::sim {

ClockId Scheduler::add_clock_mhz(std::string name, double frequency_mhz,
                                 TimestampFs phase_fs) {
  if (!std::isfinite(frequency_mhz) || frequency_mhz <= 0.0) {
    throw std::invalid_argument("clock frequency must be finite and positive");
  }
  const auto period = static_cast<TimestampFs>(
      std::llround(1'000'000'000.0 / frequency_mhz));
  if (period == 0) {
    throw std::invalid_argument("clock frequency exceeds femtosecond timebase");
  }
  const ClockId id = clocks_.size();
  clocks_.push_back(ClockDomainSnapshot{
      .name = std::move(name),
      .period_fs = period,
      .phase_fs = phase_fs,
      .next_edge_fs = phase_fs,
      .completed_cycles = 0,
  });
  return id;
}

void Scheduler::add_component(Component& component) {
  if (component.clock_id() >= clocks_.size()) {
    throw std::invalid_argument("component references an unknown clock domain");
  }
  if (std::find(components_.begin(), components_.end(), &component) !=
      components_.end()) {
    throw std::invalid_argument("component registered more than once");
  }
  components_.push_back(&component);
}

const ClockDomainSnapshot& Scheduler::clock(ClockId id) const {
  if (id >= clocks_.size()) {
    throw std::out_of_range("unknown clock domain");
  }
  return clocks_[id];
}

void Scheduler::step() {
  if (clocks_.empty()) {
    throw std::logic_error("cannot step a scheduler without clocks");
  }
  const auto next = std::min_element(
      clocks_.begin(), clocks_.end(), [](const auto& left, const auto& right) {
        return left.next_edge_fs < right.next_edge_fs;
      });
  now_fs_ = next->next_edge_fs;

  std::vector<ClockId> active_clocks;
  for (ClockId id = 0; id < clocks_.size(); ++id) {
    if (clocks_[id].next_edge_fs == now_fs_) {
      active_clocks.push_back(id);
    }
  }

  for (Component* component : components_) {
    const ClockId id = component->clock_id();
    if (clocks_[id].next_edge_fs == now_fs_) {
      component->evaluate(CycleContext{
          .now_fs = now_fs_,
          .domain_cycle = clocks_[id].completed_cycles,
          .clock_id = id,
      });
    }
  }
  for (Component* component : components_) {
    const ClockId id = component->clock_id();
    if (clocks_[id].next_edge_fs == now_fs_) {
      component->commit(CycleContext{
          .now_fs = now_fs_,
          .domain_cycle = clocks_[id].completed_cycles,
          .clock_id = id,
      });
    }
  }

  for (ClockId id : active_clocks) {
    auto& clock = clocks_[id];
    if (clock.next_edge_fs >
        std::numeric_limits<TimestampFs>::max() - clock.period_fs) {
      throw std::overflow_error("simulation timestamp overflow");
    }
    clock.next_edge_fs += clock.period_fs;
    ++clock.completed_cycles;
  }
  ++event_count_;
}

void Scheduler::run_events(std::uint64_t event_count) {
  for (std::uint64_t event = 0; event < event_count; ++event) {
    step();
  }
}

void Scheduler::run_until(const std::function<bool()>& stop,
                          std::uint64_t max_events) {
  for (std::uint64_t event = 0; event < max_events; ++event) {
    if (stop()) {
      return;
    }
    step();
  }
  if (!stop()) {
    throw std::runtime_error("simulation exceeded max_events");
  }
}

}  // namespace spine::sim
