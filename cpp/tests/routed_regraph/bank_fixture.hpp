#pragma once
#include "adapter_fixture.hpp"

namespace routed_adapter_test {
// Independent count of requests after tile, parity and cache-bank splits.
inline std::size_t bank_requests(const Data &data, std::size_t bank_lines = 128) {
  std::size_t requests = 0, first = 0;
  for (std::size_t base = 0; base < data.partition.vertices && first * 16 < data.partition.slots; base += 1024) {
    const auto last_row = std::min(base + 1024, data.partition.vertices) - 1;
    const auto last = data.rows[last_row * 2] / 16;
    while (first < last) {
      const auto end = std::min<std::size_t>(first + 2 * bank_lines, last);
      for (unsigned parity = 0; parity < 2; ++parity) {
        const auto lo = (first + 1 - parity) / 2, hi = (end + 1 - parity) / 2;
        if (hi > lo) {
          ++requests;
          if (lo < data.partition.cache_segments_per_half && hi > data.partition.cache_segments_per_half)
            ++requests;
        }
      }
      first = end;
    }
  }
  return requests;
}
} // namespace routed_adapter_test
