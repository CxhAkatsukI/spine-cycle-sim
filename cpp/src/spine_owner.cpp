#include "spine_sim/spine_owner.hpp"

#include <algorithm>
#include <limits>
#include <stdexcept>
#include <utility>

namespace spine::sim {

SpineOwnerScheduler::SpineOwnerScheduler(
    std::string name, ClockId clock_id, SpineOwnerSchedulerConfig config)
    : Component(std::move(name), clock_id), config_(config),
      owner_queues_(config.partitions),
      reactivation_queues_(config.partitions),
      staged_dispatches_(config.partitions),
      staged_completions_(config.partitions),
      staged_requeues_(config.partitions) {
  if (config_.max_vertices == 0 || config_.partitions == 0 ||
      config_.vertices_per_partition == 0 ||
      config_.owner_fifo_depth == 0 ||
      config_.reactivation_fifo_depth == 0 ||
      config_.partitions >
          std::numeric_limits<std::size_t>::max() /
              config_.vertices_per_partition ||
      config_.partitions * config_.vertices_per_partition <
          config_.max_vertices) {
    throw std::invalid_argument("invalid Spine owner scheduler geometry");
  }
}

std::size_t SpineOwnerScheduler::partition_for(std::uint32_t key) const {
  if (key >= config_.max_vertices) {
    throw std::out_of_range("Spine owner key exceeds the bounded vertex domain");
  }
  const std::size_t partition = key / config_.vertices_per_partition;
  if (partition >= config_.partitions) {
    throw std::logic_error("Spine owner key has no physical partition");
  }
  return partition;
}

SpineOwnerKeyState SpineOwnerScheduler::state(std::uint32_t key) const noexcept {
  const auto found = states_.find(key);
  return found == states_.end() ? SpineOwnerKeyState{} : found->second;
}

const std::uint32_t *SpineOwnerScheduler::owner_front(
    std::size_t partition) const {
  if (partition >= config_.partitions) {
    throw std::out_of_range("Spine owner partition is out of range");
  }
  return owner_queues_[partition].empty() ? nullptr
                                         : &owner_queues_[partition].front();
}

std::size_t SpineOwnerScheduler::owner_size(std::size_t partition) const {
  if (partition >= config_.partitions) {
    throw std::out_of_range("Spine owner partition is out of range");
  }
  return owner_queues_[partition].size();
}

std::size_t SpineOwnerScheduler::reactivation_size(
    std::size_t partition) const {
  if (partition >= config_.partitions) {
    throw std::out_of_range("Spine reactivation partition is out of range");
  }
  return reactivation_queues_[partition].size();
}

bool SpineOwnerScheduler::quiescent() const noexcept {
  if (work_credits_ != 0 || staged_activation_.has_value()) {
    return false;
  }
  const auto staged = [](const auto &items) {
    return std::any_of(items.begin(), items.end(),
                       [](const auto &item) { return item.has_value(); });
  };
  return !staged(staged_dispatches_) && !staged(staged_completions_) &&
         !staged(staged_requeues_);
}

std::uint64_t SpineOwnerScheduler::structural_credits() const noexcept {
  std::uint64_t credits = 0;
  for (const auto &queue : owner_queues_) {
    credits += queue.size();
  }
  for (const auto &queue : reactivation_queues_) {
    credits += queue.size();
  }
  for (const auto &[key, key_state] : states_) {
    static_cast<void>(key);
    credits += key_state.in_flight ? 1U : 0U;
  }
  return credits;
}

bool SpineOwnerScheduler::ledger_closed() const noexcept {
  return stats_.work_credits_created >= stats_.work_credits_retired &&
         work_credits_ ==
             stats_.work_credits_created - stats_.work_credits_retired &&
         work_credits_ == structural_credits();
}

SpineOwnerKeyState &SpineOwnerScheduler::mutable_state(std::uint32_t key) {
  return states_[key];
}

std::size_t SpineOwnerScheduler::reserved_owner_enqueues(
    std::size_t partition) const noexcept {
  std::size_t reserved = staged_requeues_[partition].has_value() ? 1 : 0;
  if (staged_activation_.has_value() &&
      staged_activation_->partition == partition &&
      staged_activation_->action == ActivationAction::kInitial) {
    ++reserved;
  }
  return reserved;
}

bool SpineOwnerScheduler::try_activate(std::uint32_t key) {
  ++stats_.activation_attempts;
  const std::size_t partition = partition_for(key);
  if (staged_activation_.has_value()) {
    ++stats_.activation_backpressure_cycles;
    return false;
  }
  const SpineOwnerKeyState current = state(key);
  if (!current.queued && !current.in_flight && !current.dirty) {
    if (owner_queues_[partition].size() +
            reserved_owner_enqueues(partition) >=
        config_.owner_fifo_depth) {
      ++stats_.owner_fifo_backpressure_cycles;
      ++stats_.activation_backpressure_cycles;
      return false;
    }
    staged_activation_ =
        StagedActivation{key, partition, ActivationAction::kInitial};
    return true;
  }
  if (current.in_flight && !current.dirty) {
    if (reactivation_queues_[partition].size() >=
        config_.reactivation_fifo_depth) {
      ++stats_.reactivation_fifo_backpressure_cycles;
      ++stats_.activation_backpressure_cycles;
      return false;
    }
    staged_activation_ =
        StagedActivation{key, partition, ActivationAction::kReactivation};
    return true;
  }
  staged_activation_ =
      StagedActivation{key, partition, ActivationAction::kCoalesced};
  return true;
}

bool SpineOwnerScheduler::try_dispatch(std::size_t partition,
                                       std::uint32_t &key) {
  if (partition >= config_.partitions) {
    throw std::out_of_range("Spine owner partition is out of range");
  }
  if (staged_dispatches_[partition].has_value() ||
      owner_queues_[partition].empty()) {
    return false;
  }
  key = owner_queues_[partition].front();
  const SpineOwnerKeyState current = state(key);
  if (!current.queued || current.in_flight) {
    throw std::logic_error("Spine owner FIFO and key state diverged");
  }
  staged_dispatches_[partition] = key;
  return true;
}

bool SpineOwnerScheduler::try_complete(std::uint32_t key) {
  const std::size_t partition = partition_for(key);
  if (staged_completions_[partition].has_value()) {
    return false;
  }
  const SpineOwnerKeyState current = state(key);
  if (!current.in_flight) {
    return false;
  }
  staged_completions_[partition] = key;
  return true;
}

void SpineOwnerScheduler::evaluate(const CycleContext &) {
  for (std::size_t partition = 0; partition < config_.partitions;
       ++partition) {
    if (staged_requeues_[partition].has_value() ||
        reactivation_queues_[partition].empty()) {
      continue;
    }
    const std::uint32_t key = reactivation_queues_[partition].front();
    const SpineOwnerKeyState current = state(key);
    if (!current.dirty) {
      throw std::logic_error("Spine reactivation FIFO lost its dirty state");
    }
    if (current.in_flight || current.queued) {
      continue;
    }
    if (owner_queues_[partition].size() +
            reserved_owner_enqueues(partition) >=
        config_.owner_fifo_depth) {
      ++stats_.owner_fifo_backpressure_cycles;
      continue;
    }
    staged_requeues_[partition] = key;
  }
}

void SpineOwnerScheduler::update_maxima() noexcept {
  for (const auto &queue : owner_queues_) {
    stats_.max_owner_fifo_occupancy =
        std::max(stats_.max_owner_fifo_occupancy, queue.size());
  }
  for (const auto &queue : reactivation_queues_) {
    stats_.max_reactivation_fifo_occupancy =
        std::max(stats_.max_reactivation_fifo_occupancy, queue.size());
  }
  stats_.max_work_credits =
      std::max(stats_.max_work_credits, work_credits_);
}

void SpineOwnerScheduler::commit(const CycleContext &) {
  for (std::size_t partition = 0; partition < config_.partitions;
       ++partition) {
    if (!staged_dispatches_[partition].has_value()) {
      continue;
    }
    const std::uint32_t key = *staged_dispatches_[partition];
    if (owner_queues_[partition].empty() ||
        owner_queues_[partition].front() != key) {
      throw std::logic_error("Spine owner dispatch changed before commit");
    }
    owner_queues_[partition].pop_front();
    SpineOwnerKeyState &current = mutable_state(key);
    current.queued = false;
    current.in_flight = true;
    ++stats_.dispatches;
  }

  for (std::size_t partition = 0; partition < config_.partitions;
       ++partition) {
    if (!staged_completions_[partition].has_value()) {
      continue;
    }
    const std::uint32_t key = *staged_completions_[partition];
    SpineOwnerKeyState &current = mutable_state(key);
    if (!current.in_flight || work_credits_ == 0) {
      throw std::logic_error("Spine owner completion has no work credit");
    }
    current.in_flight = false;
    --work_credits_;
    ++stats_.work_credits_retired;
    ++stats_.completions;
  }

  if (staged_activation_.has_value()) {
    const StagedActivation activation = *staged_activation_;
    SpineOwnerKeyState &current = mutable_state(activation.key);
    switch (activation.action) {
      case ActivationAction::kInitial:
        owner_queues_[activation.partition].push_back(activation.key);
        current.queued = true;
        ++work_credits_;
        ++stats_.work_credits_created;
        ++stats_.initial_activations;
        break;
      case ActivationAction::kReactivation:
        reactivation_queues_[activation.partition].push_back(activation.key);
        current.dirty = true;
        ++work_credits_;
        ++stats_.work_credits_created;
        ++stats_.reactivations;
        break;
      case ActivationAction::kCoalesced:
        ++stats_.coalesced_activations;
        break;
    }
  }

  for (std::size_t partition = 0; partition < config_.partitions;
       ++partition) {
    if (!staged_requeues_[partition].has_value()) {
      continue;
    }
    const std::uint32_t key = *staged_requeues_[partition];
    if (reactivation_queues_[partition].empty() ||
        reactivation_queues_[partition].front() != key) {
      throw std::logic_error("Spine reactivation changed before commit");
    }
    reactivation_queues_[partition].pop_front();
    owner_queues_[partition].push_back(key);
    SpineOwnerKeyState &current = mutable_state(key);
    current.dirty = false;
    current.queued = true;
    ++stats_.reactivation_requeues;
  }

  staged_activation_.reset();
  for (std::size_t partition = 0; partition < config_.partitions;
       ++partition) {
    staged_dispatches_[partition].reset();
    staged_completions_[partition].reset();
    staged_requeues_[partition].reset();
  }
  update_maxima();
  if (!ledger_closed()) {
    throw std::logic_error("Spine owner work-credit ledger diverged");
  }
  for (auto iterator = states_.begin(); iterator != states_.end();) {
    if (iterator->second == SpineOwnerKeyState{}) {
      iterator = states_.erase(iterator);
    } else {
      ++iterator;
    }
  }
}

}  // namespace spine::sim
