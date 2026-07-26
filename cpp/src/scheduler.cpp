#include "spine_sim/scheduler.hpp"

#include <algorithm>
#include <chrono>
#include <cmath>
#include <cstdlib>
#include <iostream>
#include <limits>
#include <stdexcept>
#include <utility>

namespace spine::sim {

namespace {

std::uint64_t profiling_period_from_environment() {
  const char* text = std::getenv("SPINE_SIM_PROFILE_COMPONENT_PERIOD");
  if (text == nullptr || *text == '\0') {
    return 0;
  }
  try {
    const std::string value(text);
    std::size_t consumed = 0;
    const std::uint64_t period = std::stoull(value, &consumed);
    if (consumed != value.size() || period == 0) {
      throw std::invalid_argument("not a positive integer");
    }
    return period;
  } catch (const std::exception& error) {
    throw std::invalid_argument(
        std::string("invalid SPINE_SIM_PROFILE_COMPONENT_PERIOD: ") +
        error.what());
  }
}

}  // namespace

Scheduler::Scheduler()
    : profiling_period_(profiling_period_from_environment()),
      emit_profile_report_(
          std::getenv("SPINE_SIM_PROFILE_COMPONENT_REPORT") != nullptr) {}

Scheduler::~Scheduler() {
  if (!emit_profile_report_ || profiling_period_ == 0) {
    return;
  }
  std::cerr << "SCHEDULER_PROFILE period=" << profiling_period_ << '\n';
  for (const SchedulerComponentProfile& row : component_profile()) {
    std::cerr << "SCHEDULER_PROFILE component=" << row.name
              << " prepare_samples=" << row.prepare_samples
              << " prepare_ns=" << row.prepare_nanoseconds
              << " evaluate_samples=" << row.evaluate_samples
              << " evaluate_ns=" << row.evaluate_nanoseconds
              << " commit_samples=" << row.commit_samples
              << " commit_ns=" << row.commit_nanoseconds << '\n';
  }
}

std::vector<SchedulerComponentProfile> Scheduler::component_profile() const {
  std::vector<SchedulerComponentProfile> rows;
  rows.reserve(profiles_.size());
  for (const auto& [component, profile] : profiles_) {
    (void)component;
    rows.push_back(profile);
  }
  std::sort(rows.begin(), rows.end(), [](const auto& left, const auto& right) {
    const std::uint64_t left_total = left.prepare_nanoseconds +
                                     left.evaluate_nanoseconds +
                                     left.commit_nanoseconds;
    const std::uint64_t right_total = right.prepare_nanoseconds +
                                      right.evaluate_nanoseconds +
                                      right.commit_nanoseconds;
    return left_total != right_total ? left_total > right_total
                                     : left.name < right.name;
  });
  return rows;
}

void Scheduler::record_profile(Component& component, ProfilePhase phase,
                               std::uint64_t nanoseconds) {
  SchedulerComponentProfile& row = profiles_.at(&component);
  switch (phase) {
    case ProfilePhase::kPrepare:
      ++row.prepare_samples;
      row.prepare_nanoseconds += nanoseconds;
      return;
    case ProfilePhase::kEvaluate:
      ++row.evaluate_samples;
      row.evaluate_nanoseconds += nanoseconds;
      return;
    case ProfilePhase::kCommit:
      ++row.commit_samples;
      row.commit_nanoseconds += nanoseconds;
      return;
  }
}

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
  if (profiling_period_ != 0) {
    profiles_.emplace(&component,
                      SchedulerComponentProfile{.name = component.name()});
  }
  if (component.has_prepare_phase()) {
    prepare_components_.push_back(&component);
  }
  if (component.has_evaluate_phase()) {
    evaluate_components_.push_back(&component);
    evaluate_dynamic_guards_.push_back(
        component.has_dynamic_evaluate_guard());
  }
  if (component.has_commit_phase()) {
    commit_components_.push_back(&component);
    commit_dynamic_guards_.push_back(component.has_dynamic_commit_guard());
    commit_latched_guards_.push_back(component.has_latched_commit_guard());
  }
}

void Scheduler::remove_component(Component& component) {
  const auto found = std::find(components_.begin(), components_.end(), &component);
  if (found == components_.end()) {
    throw std::invalid_argument("component is not registered");
  }
  components_.erase(found);
  const auto remove_from_phase = [&component](auto& phase_components) {
    const auto phase_found =
        std::find(phase_components.begin(), phase_components.end(), &component);
    if (phase_found != phase_components.end()) {
      phase_components.erase(phase_found);
    }
  };
  const auto remove_from_guarded_phase = [&component](
                                          auto& phase_components,
                                          auto&... guards) {
    const auto phase_found =
        std::find(phase_components.begin(), phase_components.end(), &component);
    if (phase_found == phase_components.end()) {
      return;
    }
    const auto index = static_cast<std::size_t>(
        std::distance(phase_components.begin(), phase_found));
    phase_components.erase(phase_found);
    (guards.erase(guards.begin() + static_cast<std::ptrdiff_t>(index)), ...);
  };
  remove_from_phase(prepare_components_);
  remove_from_guarded_phase(evaluate_components_, evaluate_dynamic_guards_);
  remove_from_guarded_phase(commit_components_, commit_dynamic_guards_,
                            commit_latched_guards_);
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
  const bool profile_cycle =
      profiling_period_ != 0 && event_count_ % profiling_period_ == 0;
  const auto invoke = [this, profile_cycle](Component& component,
                                             ProfilePhase phase,
                                             auto&& action) {
    if (!profile_cycle) {
      action();
      return;
    }
    const auto start = std::chrono::steady_clock::now();
    action();
    const auto elapsed = std::chrono::duration_cast<std::chrono::nanoseconds>(
        std::chrono::steady_clock::now() - start);
    record_profile(component, phase,
                   static_cast<std::uint64_t>(elapsed.count()));
  };

  if (clocks_.size() == 1) {
    const CycleContext context{
        .now_fs = now_fs_,
        .domain_cycle = clocks_.front().completed_cycles,
        .clock_id = 0,
    };
    for (Component* component : prepare_components_) {
      invoke(*component, ProfilePhase::kPrepare,
             [&] { component->prepare(context); });
    }
    for (std::size_t index = 0; index < evaluate_components_.size(); ++index) {
      Component* component = evaluate_components_[index];
      if (evaluate_dynamic_guards_[index] && !component->evaluate_ready()) {
        continue;
      }
      invoke(*component, ProfilePhase::kEvaluate,
             [&] { component->evaluate(context); });
    }
    commit_readiness_.resize(commit_components_.size());
    for (std::size_t index = 0; index < commit_components_.size(); ++index) {
      commit_readiness_[index] =
          !commit_dynamic_guards_[index] ||
          (commit_latched_guards_[index]
               ? commit_components_[index]->latched_commit_ready()
               : commit_components_[index]->commit_ready());
    }
    for (std::size_t index = 0; index < commit_components_.size(); ++index) {
      if (!commit_readiness_[index]) {
        continue;
      }
      Component* component = commit_components_[index];
      invoke(*component, ProfilePhase::kCommit,
             [&] { component->commit(context); });
    }
  } else {
    for (Component* component : prepare_components_) {
      const ClockId id = component->clock_id();
      if (clocks_[id].next_edge_fs == now_fs_) {
        const CycleContext context{
            .now_fs = now_fs_,
            .domain_cycle = clocks_[id].completed_cycles,
            .clock_id = id,
        };
        invoke(*component, ProfilePhase::kPrepare,
               [&] { component->prepare(context); });
      }
    }
    for (std::size_t index = 0; index < evaluate_components_.size(); ++index) {
      Component* component = evaluate_components_[index];
      const ClockId id = component->clock_id();
      if (clocks_[id].next_edge_fs == now_fs_ &&
          (!evaluate_dynamic_guards_[index] || component->evaluate_ready())) {
        const CycleContext context{
            .now_fs = now_fs_,
            .domain_cycle = clocks_[id].completed_cycles,
            .clock_id = id,
        };
        invoke(*component, ProfilePhase::kEvaluate,
               [&] { component->evaluate(context); });
      }
    }
    commit_readiness_.resize(commit_components_.size());
    for (std::size_t index = 0; index < commit_components_.size(); ++index) {
      Component* component = commit_components_[index];
      const ClockId id = component->clock_id();
      commit_readiness_[index] =
          clocks_[id].next_edge_fs == now_fs_ &&
          (!commit_dynamic_guards_[index] ||
           (commit_latched_guards_[index]
                ? component->latched_commit_ready()
                : component->commit_ready()));
    }
    for (std::size_t index = 0; index < commit_components_.size(); ++index) {
      if (!commit_readiness_[index]) {
        continue;
      }
      Component* component = commit_components_[index];
      const ClockId id = component->clock_id();
      {
        const CycleContext context{
            .now_fs = now_fs_,
            .domain_cycle = clocks_[id].completed_cycles,
            .clock_id = id,
        };
        invoke(*component, ProfilePhase::kCommit,
               [&] { component->commit(context); });
      }
    }
  }

  for (auto& clock : clocks_) {
    if (clock.next_edge_fs != now_fs_) {
      continue;
    }
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
