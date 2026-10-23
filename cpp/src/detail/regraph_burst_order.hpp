#pragma once

#include <array>
#include <cstddef>
#include <stdexcept>

namespace spine::sim::detail {

enum class ReGraphBurstOrder { kSequential, kFourWorkerAddressed };

// Four monotonic shard streams prove unique coverage without a graph-sized bitmap.
class ReGraphBurstCoverage {
public:
  explicit ReGraphBurstCoverage(ReGraphBurstOrder mode = ReGraphBurstOrder::kSequential)
      : mode_(mode) {}
  void reset(std::size_t vertices) {
    if (!vertices || vertices % 16 || (addressed() && vertices % 65536))
      throw std::invalid_argument("invalid ReGraph burst coverage shape");
    vertices_ = vertices;
    accepted_ = 0;
    next_ = {0, 65536, 131072, 196608};
  }
  void accept(std::size_t offset) {
    if (offset >= vertices_ || offset % 16 || accepted_ == vertices_ / 16)
      throw std::logic_error("ReGraph burst offset outside unique coverage");
    if (!addressed()) {
      if (offset != accepted_ * 16)
        throw std::logic_error("ReGraph sequential burst out of order");
    } else {
      auto& next = next_[(offset / 65536) % 4];
      if (offset != next)
        throw std::logic_error("ReGraph addressed burst missing, duplicated or reordered");
      next = (offset % 65536 == 65520) ? (offset / 65536 + 4) * 65536 : offset + 16;
    }
    ++accepted_;
  }
  [[nodiscard]] bool addressed() const noexcept {
    return mode_ == ReGraphBurstOrder::kFourWorkerAddressed;
  }
private:
  ReGraphBurstOrder mode_;
  std::size_t vertices_{}, accepted_{};
  std::array<std::size_t, 4> next_{};
};

} // namespace spine::sim::detail
