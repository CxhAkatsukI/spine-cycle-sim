#pragma once

#include <algorithm>
#include <deque>
#include <optional>
#include <stdexcept>
#include <utility>

#include "spine_sim/original_regraph/types.hpp"

namespace spine::sim::original_regraph::detail {

// Registered finite in-flight storage. A retirement on this edge does not
// create same-edge acceptance space. Components stage actions in evaluate().
template <typename T>
class LatencyPipe {
 public:
  explicit LatencyPipe(PipelineTiming timing) : timing_(timing) {
    if (!timing.latency || !timing.initiation_interval || !timing.capacity) {
      throw std::invalid_argument("pipeline timing must be positive");
    }
  }

  bool can_accept(std::uint64_t cycle) {
    if (values_.size() == timing_.capacity) {
      ++counters_.capacity_stalls;
      return false;
    }
    if (last_accept_ && cycle - *last_accept_ < timing_.initiation_interval) {
      ++counters_.interval_stalls;
      return false;
    }
    return true;
  }

  void stage_accept(T value, std::uint64_t cycle) {
    if (accepted_ || !can_accept(cycle)) {
      throw std::logic_error("pipeline acceptance without capacity");
    }
    accepted_ = Entry{cycle + timing_.latency, std::move(value)};
  }

  const T* ready(std::uint64_t cycle) const noexcept {
    return !values_.empty() && values_.front().due <= cycle
               ? &values_.front().value : nullptr;
  }

  void stage_retire() {
    if (retire_ || values_.empty()) {
      throw std::logic_error("invalid pipeline retirement");
    }
    retire_ = true;
  }

  void output_stall() noexcept { ++counters_.output_stalls; }

  void commit(std::uint64_t cycle) {
    if (retire_) {
      values_.pop_front();
      retire_ = false;
      ++counters_.completed;
    }
    if (accepted_) {
      values_.push_back(std::move(*accepted_));
      accepted_.reset();
      last_accept_ = cycle;
      ++counters_.accepted;
      counters_.max_inflight = std::max(counters_.max_inflight, values_.size());
    }
  }

  bool drained() const noexcept {
    return values_.empty() && !accepted_ && !retire_;
  }
  const PipelineCounters& counters() const noexcept { return counters_; }

 private:
  struct Entry { std::uint64_t due; T value; };
  PipelineTiming timing_;
  std::deque<Entry> values_;
  std::optional<Entry> accepted_;
  std::optional<std::uint64_t> last_accept_;
  bool retire_{};
  PipelineCounters counters_;
};

}  // namespace spine::sim::original_regraph::detail
