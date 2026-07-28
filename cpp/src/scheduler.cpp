#include "spine_sim/scheduler.hpp"

#include <algorithm>
#include <bit>
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
  rebuild_phase_registrations();
}

void Scheduler::remove_component(Component& component) {
  const auto found = std::find(components_.begin(), components_.end(), &component);
  if (found == components_.end()) {
    throw std::invalid_argument("component is not registered");
  }
  components_.erase(found);
  rebuild_phase_registrations();
}

void Scheduler::notify_latched_commit(void *owner,
                                      std::size_t slot) noexcept {
  static_cast<Scheduler *>(owner)->mark_latched_commit_ready(slot);
}

void Scheduler::mark_latched_commit_ready(std::size_t slot) noexcept {
  const std::size_t word = slot / 64;
  if (word >= latched_commit_words_.size()) {
    return;
  }
  latched_commit_words_[word] |= std::uint64_t{1} << (slot % 64);
}

void Scheduler::rebuild_phase_registrations() {
  for (std::size_t slot = 0; slot < commit_components_.size(); ++slot) {
    if (commit_latched_guards_[slot]) {
      commit_components_[slot]->unbind_latched_commit_notifier();
    }
  }
  prepare_components_.clear();
  prepare_dynamic_guards_.clear();
  evaluate_components_.clear();
  evaluate_dynamic_guards_.clear();
  commit_components_.clear();
  commit_dynamic_guards_.clear();
  commit_latched_guards_.clear();
  unconditional_commit_slots_.clear();
  dynamic_commit_slots_.clear();

  for (Component *component : components_) {
    if (component->has_prepare_phase()) {
      prepare_components_.push_back(component);
      prepare_dynamic_guards_.push_back(
          component->has_dynamic_prepare_guard());
    }
    if (component->has_evaluate_phase()) {
      evaluate_components_.push_back(component);
      evaluate_dynamic_guards_.push_back(
          component->has_dynamic_evaluate_guard());
    }
    if (component->has_commit_phase()) {
      commit_components_.push_back(component);
      commit_dynamic_guards_.push_back(
          component->has_dynamic_commit_guard());
      commit_latched_guards_.push_back(
          component->has_latched_commit_guard());
    }
  }

  const std::size_t word_count = (commit_components_.size() + 63) / 64;
  latched_commit_words_.assign(word_count, 0);
  selected_commit_words_.assign(word_count, 0);
  for (std::size_t slot = 0; slot < commit_components_.size(); ++slot) {
    Component *component = commit_components_[slot];
    if (commit_latched_guards_[slot]) {
      component->bind_latched_commit_notifier(
          this, slot, &Scheduler::notify_latched_commit);
      if (component->latched_commit_ready()) {
        mark_latched_commit_ready(slot);
      }
    } else if (commit_dynamic_guards_[slot]) {
      dynamic_commit_slots_.push_back(slot);
    } else {
      unconditional_commit_slots_.push_back(slot);
    }
  }
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
  const auto select_commit = [this](std::size_t slot) {
    selected_commit_words_[slot / 64] |=
        std::uint64_t{1} << (slot % 64);
  };
  const auto invoke_selected_commits =
      [this, &invoke](const auto &context_for_slot) {
        for (std::size_t word_index = 0;
             word_index < selected_commit_words_.size(); ++word_index) {
          std::uint64_t word = selected_commit_words_[word_index];
          while (word != 0) {
            const unsigned bit = std::countr_zero(word);
            const std::size_t slot = word_index * 64 + bit;
            Component *component = commit_components_[slot];
            const CycleContext context = context_for_slot(slot);
            invoke(*component, ProfilePhase::kCommit,
                   [&] { component->commit(context); });
            word &= word - 1;
          }
        }
      };

  if (clocks_.size() == 1) {
    const CycleContext context{
        .now_fs = now_fs_,
        .domain_cycle = clocks_.front().completed_cycles,
        .clock_id = 0,
    };
    for (std::size_t index = 0; index < prepare_components_.size(); ++index) {
      Component *component = prepare_components_[index];
      if (prepare_dynamic_guards_[index] && !component->prepare_ready()) {
        continue;
      }
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
    selected_commit_words_ = latched_commit_words_;
    std::fill(latched_commit_words_.begin(), latched_commit_words_.end(), 0);
    for (const std::size_t slot : unconditional_commit_slots_) {
      select_commit(slot);
    }
    for (const std::size_t slot : dynamic_commit_slots_) {
      if (commit_components_[slot]->commit_ready()) {
        select_commit(slot);
      }
    }
    invoke_selected_commits([&context](std::size_t) { return context; });
  } else {
    for (std::size_t index = 0; index < prepare_components_.size(); ++index) {
      Component *component = prepare_components_[index];
      const ClockId id = component->clock_id();
      if (clocks_[id].next_edge_fs == now_fs_ &&
          (!prepare_dynamic_guards_[index] || component->prepare_ready())) {
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
    std::fill(selected_commit_words_.begin(), selected_commit_words_.end(), 0);
    for (std::size_t word_index = 0;
         word_index < latched_commit_words_.size(); ++word_index) {
      std::uint64_t pending = latched_commit_words_[word_index];
      while (pending != 0) {
        const unsigned bit = std::countr_zero(pending);
        const std::size_t slot = word_index * 64 + bit;
        Component *component = commit_components_[slot];
        if (clocks_[component->clock_id()].next_edge_fs == now_fs_) {
          select_commit(slot);
          latched_commit_words_[word_index] &=
              ~(std::uint64_t{1} << bit);
        }
        pending &= pending - 1;
      }
    }
    for (const std::size_t slot : unconditional_commit_slots_) {
      Component *component = commit_components_[slot];
      if (clocks_[component->clock_id()].next_edge_fs == now_fs_) {
        select_commit(slot);
      }
    }
    for (const std::size_t slot : dynamic_commit_slots_) {
      Component *component = commit_components_[slot];
      if (clocks_[component->clock_id()].next_edge_fs == now_fs_ &&
          component->commit_ready()) {
        select_commit(slot);
      }
    }
    invoke_selected_commits([this](std::size_t slot) {
      const ClockId id = commit_components_[slot]->clock_id();
      return CycleContext{
          .now_fs = now_fs_,
          .domain_cycle = clocks_[id].completed_cycles,
          .clock_id = id,
      };
    });
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
