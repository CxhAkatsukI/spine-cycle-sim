#pragma once

#include <algorithm>
#include <cstddef>
#include <cstdint>
#include <deque>
#include <optional>
#include <stdexcept>
#include <string>
#include <utility>

#include "spine_sim/component.hpp"

namespace spine::sim {

struct FifoStats {
  std::uint64_t pushes{};
  std::uint64_t pops{};
  std::uint64_t push_stalls{};
  std::uint64_t pop_stalls{};
  std::size_t max_occupancy{};
};

// A strict registered SPSC queue. A push committed on edge N is visible to a
// consumer evaluating edge N+1; simultaneous pop does not create fall-through
// space for a producer on a full queue.
template <typename T>
class Fifo final : public Component {
 public:
  using NonemptyNotifier = void (*)(void*) noexcept;
  using NonfullNotifier = void (*)(void*) noexcept;

  Fifo(std::string name, ClockId clock_id, std::size_t depth)
      : Component(std::move(name), clock_id), depth_(depth) {
    if (depth_ == 0) {
      throw std::invalid_argument("FIFO depth must be positive");
    }
  }

  [[nodiscard]] std::size_t depth() const noexcept { return depth_; }
  [[nodiscard]] std::size_t size() const noexcept { return queue_.size(); }
  [[nodiscard]] bool empty() const noexcept { return queue_.empty(); }
  [[nodiscard]] bool full() const noexcept { return queue_.size() == depth_; }
  [[nodiscard]] const FifoStats& stats() const noexcept { return stats_; }

  void account_pop_stalls(std::uint64_t count) noexcept {
    stats_.pop_stalls += count;
  }

  void account_push_stalls(std::uint64_t count) noexcept {
    stats_.push_stalls += count;
  }

  void bind_nonempty_notifier(void* owner, NonemptyNotifier notifier) {
    if (notifier == nullptr ||
        (nonempty_notifier_ != nullptr &&
         (nonempty_notifier_owner_ != owner ||
          nonempty_notifier_ != notifier))) {
      throw std::logic_error("FIFO nonempty notifier is already bound");
    }
    nonempty_notifier_owner_ = owner;
    nonempty_notifier_ = notifier;
  }

  void unbind_nonempty_notifier(void* owner) noexcept {
    if (nonempty_notifier_owner_ != owner) {
      return;
    }
    nonempty_notifier_owner_ = nullptr;
    nonempty_notifier_ = nullptr;
  }

  void bind_nonfull_notifier(void* owner, NonfullNotifier notifier) {
    if (notifier == nullptr ||
        (nonfull_notifier_ != nullptr &&
         (nonfull_notifier_owner_ != owner ||
          nonfull_notifier_ != notifier))) {
      throw std::logic_error("FIFO nonfull notifier is already bound");
    }
    nonfull_notifier_owner_ = owner;
    nonfull_notifier_ = notifier;
  }

  void unbind_nonfull_notifier(void* owner) noexcept {
    if (nonfull_notifier_owner_ != owner) {
      return;
    }
    nonfull_notifier_owner_ = nullptr;
    nonfull_notifier_ = nullptr;
  }

  void reset_stats() {
    if (!queue_.empty() || staged_push_.has_value() || staged_pop_) {
      throw std::logic_error("FIFO statistics require a drained queue");
    }
    stats_ = {};
  }

  [[nodiscard]] const T* front() const noexcept {
    return queue_.empty() ? nullptr : &queue_.front();
  }

  bool try_push(const T& value) {
    if (staged_push_.has_value() || full()) {
      ++stats_.push_stalls;
      return false;
    }
    staged_push_ = value;
    set_latched_commit_ready(true);
    return true;
  }

  bool try_push(T&& value) {
    if (staged_push_.has_value() || full()) {
      ++stats_.push_stalls;
      return false;
    }
    staged_push_ = std::move(value);
    set_latched_commit_ready(true);
    return true;
  }

  bool try_pop(T& value) {
    if (staged_pop_ || queue_.empty()) {
      ++stats_.pop_stalls;
      return false;
    }
    value = queue_.front();
    staged_pop_ = true;
    set_latched_commit_ready(true);
    return true;
  }

  [[nodiscard]] bool has_evaluate_phase() const noexcept override {
    return false;
  }
  [[nodiscard]] bool has_dynamic_commit_guard() const noexcept override {
    return true;
  }
  [[nodiscard]] bool has_latched_commit_guard() const noexcept override {
    return true;
  }
  void evaluate(const CycleContext&) override {}

  void commit(const CycleContext&) override {
    const bool was_full = full();
    if (staged_pop_) {
      queue_.pop_front();
      staged_pop_ = false;
      ++stats_.pops;
    }
    if (staged_push_.has_value()) {
      queue_.push_back(std::move(*staged_push_));
      staged_push_.reset();
      ++stats_.pushes;
      if (nonempty_notifier_ != nullptr) {
        nonempty_notifier_(nonempty_notifier_owner_);
      }
    }
    if (was_full && !full() && nonfull_notifier_ != nullptr) {
      nonfull_notifier_(nonfull_notifier_owner_);
    }
    stats_.max_occupancy = std::max(stats_.max_occupancy, queue_.size());
    set_latched_commit_ready(false);
  }

 private:
  std::size_t depth_;
  std::deque<T> queue_;
  std::optional<T> staged_push_;
  bool staged_pop_{};
  void* nonempty_notifier_owner_{};
  NonemptyNotifier nonempty_notifier_{};
  void* nonfull_notifier_owner_{};
  NonfullNotifier nonfull_notifier_{};
  FifoStats stats_;
};

}  // namespace spine::sim
