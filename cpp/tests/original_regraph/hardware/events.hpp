#pragma once

#include "model.hpp"

namespace original_r_board {
struct Times {
  std::uint64_t queued{}, submitted{}, start{}, end{};
  void validate() const {
    require(queued <= submitted && submitted <= start && start < end, "invalid kernel event timestamps");
  }
};

struct Window { std::uint64_t busy_ns{}, span_ns{}; };

inline Window window(const std::vector<Times>& events) {
  require(!events.empty(), "nonempty kernel event window required");
  std::vector<std::pair<std::uint64_t, std::uint64_t>> intervals;
  for (const auto& event : events) {
    event.validate(); intervals.emplace_back(event.start, event.end);
  }
  std::sort(intervals.begin(), intervals.end());
  auto end = intervals.front().first;
  std::uint64_t busy = 0;
  for (const auto& interval : intervals) {
    if (interval.second > end) busy += interval.second - std::max(interval.first, end);
    end = std::max(end, interval.second);
  }
  return {busy, end - intervals.front().first};
}
}  // namespace original_r_board
