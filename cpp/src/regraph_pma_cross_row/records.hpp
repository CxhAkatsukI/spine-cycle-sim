#pragma once

#include <cstddef>
#include <cstdint>
#include <vector>

namespace spine::sim::detail {
struct PmaSegmentTask {
  std::size_t source{}, begin{}, end{}, segment{};
  bool terminal{};
};
struct PmaLoadedSegment {
  PmaSegmentTask task;
  std::vector<std::uint8_t> bytes;
};
} // namespace spine::sim::detail
