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

  [[nodiscard]] const T* front() const noexcept {
    return queue_.empty() ? nullptr : &queue_.front();
  }

  bool try_push(const T& value) {
    if (staged_push_.has_value() || full()) {
      ++stats_.push_stalls;
      return false;
    }
    staged_push_ = value;
    return true;
  }

  bool try_push(T&& value) {
    if (staged_push_.has_value() || full()) {
      ++stats_.push_stalls;
      return false;
    }
    staged_push_ = std::move(value);
    return true;
  }

  bool try_pop(T& value) {
    if (staged_pop_ || queue_.empty()) {
      ++stats_.pop_stalls;
      return false;
    }
    value = queue_.front();
    staged_pop_ = true;
    return true;
  }

  void evaluate(const CycleContext&) override {}

  void commit(const CycleContext&) override {
    if (staged_pop_) {
      queue_.pop_front();
      staged_pop_ = false;
      ++stats_.pops;
    }
    if (staged_push_.has_value()) {
      queue_.push_back(std::move(*staged_push_));
      staged_push_.reset();
      ++stats_.pushes;
    }
    stats_.max_occupancy = std::max(stats_.max_occupancy, queue_.size());
  }

 private:
  std::size_t depth_;
  std::deque<T> queue_;
  std::optional<T> staged_push_;
  bool staged_pop_{};
  FifoStats stats_;
};

}  // namespace spine::sim
